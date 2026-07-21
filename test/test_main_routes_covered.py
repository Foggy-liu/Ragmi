"""回归测试：防止 `api/*.py` 里定义的 router 忘记挂载到 `main.py`。

历史教训：`api/api_vector.py` 里有 `appvector = APIRouter()` 但从未被
`main.py` 的 `include_router()` 引用，导致 `/vector` 接口永远 404，
而 dashboard 测试才暴露出来。

策略：用 AST 静态扫描 `api/*.py` 和 `main.py`，不实际 import 任何
业务模块（避免触发 Milvus / LLM 连接等副作用）。

关键边界：模块级重命名（如 `from api.api_file import app as appfile`）
是合法的——只要 `appfile` 出现在 `include_router/mount` 里就算挂载。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_DIR = PROJECT_ROOT / "api"
MAIN_PY = PROJECT_ROOT / "main.py"


@dataclass(frozen=True)
class RouterDef:
    """一个 api/ 文件里定义的 router/app。"""
    name: str           # 模块里的原名（如 `app`、`appchat`）
    path: Path          # 定义所在的文件
    kind: str           # "APIRouter" 或 "FastAPI"


@dataclass(frozen=True)
class ImportInfo:
    """main.py 里的一条 import 语句。"""
    module: str         # 如 "api.api_file"
    original: str       # 模块里的原名
    alias: str          # main.py 里的本地名（alias or original）


def _parse(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def _find_router_definitions() -> dict[str, RouterDef]:
    """扫描 api/*.py，返回 {local_name: RouterDef}。

    接受 `appXxx = APIRouter()` 和 `app = FastAPI()` 两种形式。
    """
    found: dict[str, RouterDef] = {}
    for py_file in sorted(API_DIR.glob("api_*.py")):
        tree = _parse(py_file)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id == "APIRouter":
                    found[target.id] = RouterDef(target.id, py_file, "APIRouter")
                elif value.func.id == "FastAPI":
                    found[target.id] = RouterDef(target.id, py_file, "FastAPI")
    return found


def _find_main_imports() -> list[ImportInfo]:
    """main.py 里所有 `from X import Y [as Z]` 语句。"""
    tree = _parse(MAIN_PY)
    imports: list[ImportInfo] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        for alias in node.names:
            imports.append(ImportInfo(module, alias.name, alias.asname or alias.name))
    return imports


def _find_main_mount_targets() -> tuple[set[str], set[str]]:
    """返回 (included_local_names, mounted_local_names)。

    即 main.py 中 `app.include_router(X, ...)` 和 `app.mount('/p', X, ...)`
    实际使用的本地名（允许 X 是 alias 后的名字）。
    """
    tree = _parse(MAIN_PY)
    included: set[str] = set()
    mounted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "app"):
            continue
        if func.attr == "include_router" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name):
                included.add(first.id)
        elif func.attr == "mount" and len(node.args) >= 2:
            second = node.args[1]
            if isinstance(second, ast.Name):
                mounted.add(second.id)
    return included, mounted


# ---- 核心断言 ----

def test_every_router_is_imported_and_mounted():
    """每个 api/*.py 里定义的 router 都必须同时被 main.py import 并 include/mount。"""
    routers = _find_router_definitions()
    assert routers, "未在 api/*.py 中找到任何 router 定义（检查 API_DIR 是否正确）"

    imports = _find_main_imports()
    included, mounted = _find_main_mount_targets()

    # 把 import 按"模块名"分组，方便反查：源文件名 → [(original, alias), ...]
    by_module: dict[str, list[ImportInfo]] = {}
    for imp in imports:
        by_module.setdefault(imp.module, []).append(imp)

    # 诊断输出
    summary_lines = ["\n=== Router 挂载检查 ==="]
    not_imported: list[RouterDef] = []
    not_mounted: list[tuple[RouterDef, str]] = []

    for router in routers.values():
        # 期望的模块路径，如 `api.api_chat`
        expected_module = "api." + router.path.stem
        matching_imports = by_module.get(expected_module, [])
        # 找一条把 router.name 导入的 import（不管 alias 是什么）
        matched = [imp for imp in matching_imports if imp.original == router.name]

        if not matched:
            not_imported.append(router)
            status = "MISSING-import"
        else:
            # 至少有一条 import 命中，再看 alias 是否出现在 include/mount 里
            aliases = {imp.alias for imp in matched}
            mounted_aliases = aliases & (included | mounted)
            if mounted_aliases:
                status = "include" if mounted_aliases & included else "mount"
            else:
                status = "MISSING-mount"
                not_mounted.append((router, next(iter(aliases))))

        kind_tag = f"[{router.kind}]"
        summary_lines.append(
            f"  {'OK' if 'MISSING' not in status else 'FAIL'} "
            f"{router.name:12s} {kind_tag:12s} ({router.path.relative_to(PROJECT_ROOT)}) [{status}]"
        )

    print("\n".join(summary_lines))

    if not_imported:
        names = "\n".join(
            f"  - {r.name} ({r.path.relative_to(PROJECT_ROOT)}) → "
            f"期望模块路径 `api.{r.path.stem}`"
            for r in not_imported
        )
        pytest.fail(
            f"以下 router 定义了但 main.py 没 import:\n{names}\n"
            f"修复：在 main.py 加 `from api.<module> import <name>`"
        )

    if not_mounted:
        lines = "\n".join(
            f"  - {r.name} (imported as `{alias}`, {r.path.relative_to(PROJECT_ROOT)})"
            for r, alias in not_mounted
        )
        pytest.fail(
            f"以下 router import 了但没挂载到 app（404 风险）:\n{lines}\n"
            f"修复：在 main.py 加 `app.include_router({alias}, tags=[...])`"
            f" 或 `app.mount('/prefix', {alias}, ...)`"
        )


def test_no_orphan_router_import():
    """main.py 不应 import 了 router 又不挂载（清理或挂载，二选一）。"""
    imports = _find_main_imports()
    included, mounted = _find_main_mount_targets()
    used = included | mounted

    orphans = [imp for imp in imports if imp.module.startswith("api.")
               and imp.alias not in used
               and imp.module.split(".")[-1].startswith("api_")]
    if orphans:
        lines = "\n".join(f"  - {imp.module}: {imp.original} as {imp.alias}" for imp in orphans)
        pytest.fail(
            f"以下 api/* 的 import 未在 main.py 中挂载（应删除 import 或挂载）:\n{lines}"
        )


# ---- 文档化 fixture：把当前状态固化下来 ----

@pytest.fixture(scope="module")
def router_coverage_report() -> dict:
    """给其他测试或调试脚本复用的报告。"""
    routers = _find_router_definitions()
    imports = _find_main_imports()
    included, mounted = _find_main_mount_targets()
    return {
        "defined": routers,
        "imports": imports,
        "included": included,
        "mounted": mounted,
    }
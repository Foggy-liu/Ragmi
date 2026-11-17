"""test/conftest.py —— pytest fixtures。

三组：
1. L2 流程测试：script（假 LLM 剧本）/ fake_llm（patch LLMmodel.create_minimax）/ fake_rag（patch _ensure_rag）
2. L3 API 测试：client（TestClient）—— 定义在 test_api_contract.py，因为
   `import main` 必须在**模块顶层**完成，且只有该模块需要付这 5 秒的导入成本
3. L4 浏览器测试：fake_backend（进程外假后端）/ streamlit_url（专用 Streamlit）

⚠️ 隔离规则（设计文档 §3.6）：
- L3（API）用例**不得** patch LLMmodel.create_minimax —— 那是 L2 专用的
- `import main` 必须在测试模块顶层（collection 期）完成，不能放进 fixture
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test.helpers import FakeLLMInstance, FakeRag, Script  # noqa: E402


# ---------------------------------------------------------------------------
# L2 · Agent 流程
# ---------------------------------------------------------------------------

@pytest.fixture
def script():
    """假 LLM 剧本。用例往 script.iter / script.synth / script.reflect 里塞返回值。"""
    return Script()


@pytest.fixture
def fake_llm(script):
    """把 LLMmodel.create_minimax 换成假件。

    ⚠️ 用 unittest.mock.patch.object 而不是 monkeypatch：
    patch.object 记录的是类属性里的**原始描述符**（staticmethod），
    退出时原样还原；monkeypatch 记录的是 getattr 结果（已解包成普通函数），
    还原后 staticmethod 语义就没了。

    ⚠️ patch 的是**类属性**，节点在 invoke 期才调 _get_llm() → 立即生效，
    不需要重建图（agent/graph.py 全文没有 LLM 构造）。
    """
    from unittest.mock import patch

    from utils.models.model_setting import LLMmodel

    instance = FakeLLMInstance(script)
    with patch.object(
        LLMmodel, "create_minimax", staticmethod(lambda *args, **kwargs: instance)
    ):
        yield instance


@pytest.fixture
def fake_rag(monkeypatch):
    """替换 rag_search **底下那一层**（_ensure_rag）。

    保留的真实代码：Timer 计时 / 异常归一化 / status_wrapper 4 态分类 /
    ToolMessage 写入 / think 剥离。换成整个工具就等于把这些全排除在测试外。
    """
    import agent.tools.rag_tool as rag_tool

    rag = FakeRag()
    monkeypatch.setattr(rag_tool, "_ensure_rag", lambda: rag)
    return rag


@pytest.fixture(scope="session")
def graph():
    """真实编译出来的 LangGraph 图。

    节点每次 invoke 都懒加载 LLM，所以会话内复用同一个图是安全的。
    """
    from agent.runtime import _get_graph
    return _get_graph()


# ---------------------------------------------------------------------------
# L4 · 浏览器 E2E
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fake_backend():
    """进程外假后端（真 HTTP 服务）。

    ⚠️ 三个页面的后端调用都发生在 **Streamlit 服务端进程**里，
    Playwright 的 page.route() 一个都拦不到 —— 必须是进程外的真服务。
    """
    from test.fake_backend import create_server

    server, state = create_server()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="session")
def streamlit_url(fake_backend):
    """起一个**专用** Streamlit（8511），注入 API_BASE_URL 指向假后端。

    ⚠️ 不能复用用户已开的 Streamlit —— 复用来的进程没有 env 注入，拦截失效。
    """
    port = 8511
    env = os.environ.copy()
    env["API_BASE_URL"] = f"http://127.0.0.1:{fake_backend.port}"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "main_web.py",
            "--server.port", str(port),
            "--server.address", "127.0.0.1",
            "--server.headless", "true",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(url, timeout=90)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_for_health(url: str, timeout: float = 90.0) -> None:
    """等 Streamlit 的 /_stcore/health 变绿。"""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=3) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:      # noqa: BLE001 —— 启动期间各种异常都算"还没起来"
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Streamlit 启动超时（{timeout}s）：{last_error}")

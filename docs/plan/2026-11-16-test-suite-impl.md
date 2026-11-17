# RAGMI 测试体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **设计文档**：[`2026-11-16-test-suite-design.md`](./2026-11-16-test-suite-design.md)（v2 自审修订版）
> **落地状态文档**：[`../status/测试体系.md`](../status/测试体系.md)
> **日期**：2026-11-16　**分支**：`agent-v2.2-graph-refactor`

**Goal:** 把 RAGMI 的"流程走不走得通"变成可自动验证的东西 —— 38 条用例分 4 层落地（Agent 流程 11 / API 契约 10 / 浏览器 E2E 8 / 真环境冒烟 4 / 切分 5），一条命令能跑完。

**Architecture:** 核心是 **L2 流程层** —— 用假 LLM（按剧本返回）+ 假检索（只替换工具底下那一层）驱动**真实的 LangGraph 图**，从而测到节点逻辑、条件边路由、计数器 reducer、`Timer` 计时、异常归一化、`status_wrapper` 4 态分类、ToolMessage 写入这七段真实代码。其上依次是 L3 API 契约（TestClient + `dependency_overrides`）、L4 浏览器 E2E（进程外假后端 + 专用 Streamlit + Playwright）、L4 真环境冒烟（真 MiniMax + 真 Milvus）。

**Tech Stack:** pytest 9 / pytest-playwright / Playwright 1.58 + Chromium / FastAPI TestClient / LangGraph / `unittest.mock.patch`

> **📌 实际提交方式（2026-11-17 定案，与计划里的"每个 Task 提交一次"不同）**
>
> 按用户约定"全部等新测试体系落地后一起提交"，17 个 Task 的提交步骤**没有逐个执行**，
> 而是在体系全部落地、实测全绿之后，拆成 **4 个 commit 一次性提交**：
>
> | # | commit | 内容 |
> |---|---|---|
> | 1 | `docs: 重排文档目录` | `docs/superpowers/` → `docs/plan/` + `docs/README.md` + `.gitignore` 放行规则 |
> | 2 | `feat(agent): v2.2 图重构收尾` | `agent/` + `api/api_agent.py` + `web_page/` + `configs/` + `README.md` |
> | 3 | `test: 落地 4 层测试体系` | `test/` + `pytest.ini` + `requirements-dev.txt` + `Makefile` |
> | 4 | `docs: 补项目现状与测试体系快照` | `docs/status/` + 本计划 + `CLAUDE.md` |
>
> 下文各 Task 的"提交"步骤因此**全部标记为已完成**，但对应的 git commit 内容以上表为准。

---

## §0 动手前必须知道的 8 件事

全部来自 2026-11-16 的实跑测量（不是推断）。**违反其中任何一条，测试会假绿或假红。**

| # | 事实 | 出处 | 违反的后果 |
|---|---|---|---|
| 1 | `main.py:63` 在**模块级**调 `LLMmodel.create_minimax()` | `main.py` | patch 之后才 `import main` → 进程默认模型变假件 → `/chat` `/rag` 变成"对着假件测假件" |
| 2 | `agent/graph.py` 全文**没有 LLM 构造** | `agent/graph.py` | 以为"图缓存了 patch 没用"→ 去改 `_get_graph()` → 引入新耦合 |
| 3 | LangGraph 的 `add_messages` 按 `message.id` 去重 | langgraph | 假件复用同一个 `AIMessage` 对象 → 被当成"更新"而非"新增" → `iter_count` 少算一轮 |
| 4 | `runtime.py:95` 写死 `deadline = now + 90` | `agent/runtime.py` | 超时类用例（F9）用 `ask()` 就控制不了超时时机 → 必须直接 `graph.invoke()` |
| 5 | `api/api_agent.py:18` 的 `Field(...)` **没有** `min_length` | `api/api_agent.py` | 断言"空 query → 422" → 必然失败（实测空串是 200） |
| 6 | 三个页面的后端调用都在 **Streamlit 服务端进程**里 | `web_page/*.py` | 用 `page.route()` 拦截 → **一条都拦不到** → 整个浏览器层无法执行 |
| 7 | `sac.menu` 渲染在 iframe 里，src 形如 `/component/sac.<hash>/index.html` | `streamlit_antd_components` | 用 `iframe[src*="streamlit_antd_components"]` 找菜单 → 找不到 → E4/E5/E6 全挂 |
| 8 | `api_file.py` 上传成功后会调 `txt_main()` **全量扫 `documents/`** | `api/api_file.py:107` | C8–C10 每次跑都全量解析 → 慢 + 污染 `txt/` |

---

## §0.1 与设计文档的 4 处偏差（全部实测修正，实施时以本表为准）

| # | 设计文档写的 | 实测结果 | 本计划怎么改 |
|---|---|---|---|
| **Δ1** | F6 断言 `next_action=rewrite` | 实测 `next_action="end"` —— 第 4 次进 reflect 撞 `MAX_REFL` 强制 end；`last_critique="反思解析失败"`、`reflection_count=4`、reflect LLM 只调 3 次 | F6 改断言这 3 个值；**并在 Task 17 同步修设计文档 §4.1 F6 那行** |
| **Δ2** | F9b 断言最后一条消息 = `"回答超时：思考时间超过总时限"` | 只有当 iter **不发工具调用**时才是它。若 iter 发了工具调用，工具返回后会**再进 iter**，那次 iter 撞 `is_expired` → 消息变成 `"已达总时限，停止思考"` | F9b 的 iter 剧本改成只返回 `READY`（不发工具调用） |
| **Δ3** | E6 选择器 `iframe[src*="streamlit_antd_components"]` | 实际 src 是 `/component/sac.<hash>/index.html`（`sac._RELEASE=True` → 走本地 `frontend/build`） | 改成按 `frame.url` 匹配 `/component/sac.`（Task 15） |
| **Δ4** | 设计文档没交代 `Script` 的"用完重复最后一项"语义 | 若 F1 的 iter 剧本只写 `[tc(...)]`，iter 会一直发工具调用直到打满 `MAX_ITER` → **F1 变成 F8** | F1/F2/F3/F4 的 iter 剧本统一写成 `[tc("call_1"), READY]` —— 迭代一次就停 |

---

## §1 File Structure

```text
test/
├── __init__.py                  （已有，空）
├── conftest.py                  【新建】fixtures：假 LLM / 假检索 / 假后端 / Streamlit
├── helpers.py                   【新建】Script / FakeChat / FakeLLMInstance / FakeRag / 断言工具
├── fake_backend.py              【新建】进程外假后端（E2E 用，真 HTTP 服务）
├── test_agent_timeout.py        （已有，11 个）
├── test_main_routes_covered.py  （已有，2 个）
├── test_vector_split.py         （已有，1 个 —— 本次加 slow 标记）
├── test_agent_flow.py           【新建】F1–F11 + 公共不变式（11 条）
├── test_api_contract.py         【新建】C1–C10（10 条）
├── test_splitter.py             【新建】切分 5 条
├── test_eval_smoke.py           【新建】S1–S4（4 条，slow）
├── e2e/
│   ├── __init__.py              【新建】空文件（让 pytest 按 test.e2e.* 命名模块）
│   └── test_browser_e2e.py      【新建】E1–E8（8 条，e2e）
├── README.md                    （已有 —— Task 17 更新）
├── archive/                     （不动 —— 过时脚本的只读归档，已于 2026-11-16 由 befor/ 改名并拆成 scripts/ + data/）
└── probes/                      （不动 —— 等探针改写成 pytest 用例后再并入 archive/）

web_page/
├── rag_page.py                  【改】API 地址读 API_BASE_URL
├── rag_direct_page.py           【改】同上
└── repo_admin.py                【改】同上

pytest.ini                       【改】加 slow / e2e marker
requirements-dev.txt             【改】加 pytest-playwright
```

**依赖方向**（无环）：

```text
helpers.py  ←── conftest.py
    ↑                ↑
    │                ├── test_agent_flow.py      (L2)
    │                ├── test_api_contract.py    (L3)
    │                └── e2e/test_browser_e2e.py (L4)
    │
fake_backend.py ←── conftest.py ←── e2e/test_browser_e2e.py
```

---

## §2 任务清单

| # | 任务 | 产出 | 依赖 |
|---|---|---|---|
| 1 | 前端 API 地址读 `API_BASE_URL` | 3 个文件各 1~2 行 | — |
| 2 | `pytest.ini` 加 marker + `test_vector_split.py` 标 slow | 2 个文件 | — |
| 3 | `requirements-dev.txt` 加 `pytest-playwright` | 1 个文件 | — |
| 4 | `test/helpers.py` | 公共工具层 | — |
| 5 | `test/conftest.py` | fixtures | 4 |
| 6 | `test/test_agent_flow.py` — F1 / F1b / F1c / F2 | 4 条 | 4, 5 |
| 7 | `test/test_agent_flow.py` — F3 / F4 | 2 条 | 6 |
| 8 | `test/test_agent_flow.py` — F5 / F6 / F10 / F11 | 4 条 | 6 |
| 9 | `test/test_agent_flow.py` — F7 / F8 | 2 条 | 6 |
| 10 | `test/test_agent_flow.py` — F9a / F9b / F9c + 公共不变式 | 4 条 | 6 |
| 11 | `test/test_api_contract.py` — C1–C7 | 7 条 | 2 |
| 12 | `test/test_api_contract.py` — C8–C10 | 3 条 | 11 |
| 13 | `test/test_splitter.py` | 5 条 | — |
| 14 | `test/fake_backend.py` + conftest 的 Streamlit fixture | 假后端 | 1, 5 |
| 15 | `test/e2e/test_browser_e2e.py` — E1–E7 | 7 条 | 3, 14 |
| 16 | E8 + `test/test_eval_smoke.py` — S1–S4 | 5 条 | 15 |
| 17 | 文档同步 + 全量验收 | 4 个文档 | 全部 |

> **提交约定**：本仓库当前约定"所有改动暂不提交"。每个 Task 末尾的 `git add` / `git commit` 步骤按此约定**默认不执行**，除非用户明确要求提交。

---

## Task 1: 前端 API 地址改读 `API_BASE_URL`

**Files:**
- Modify: `web_page/rag_page.py:1-5`（加 import 与常量）、`web_page/rag_page.py:37-41`（改 url）
- Modify: `web_page/rag_direct_page.py:1-6`
- Modify: `web_page/repo_admin.py:1-11`

> **为什么这是 E2E 的前提**：三个页面的 `requests.post` 都发生在 Streamlit **服务端进程**里，浏览器拦截不到。要让浏览器层能测，就必须让 Streamlit 能被指向一个假后端 —— 唯一入口就是环境变量。
> 副作用：顺带修掉 `docs/status/项目现状.md` 的 P1-5（API 地址三套并存）。

- [x] **Step 1: 改 `web_page/rag_page.py`**

这个文件**当前没有** `API_BASE` 变量，只有一处硬编码 `url=`。要改的是**那一行**，不是"新建变量然后忘了改 url"。

```python
import os

import streamlit as st
from streamlit_extras.bottom_container import bottom
import requests

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
```

把 `web_page/rag_page.py` 里这段：

```python
                    response = requests.post(
                        url="http://localhost:8000/agent/chat",
                        json={"query": query},
                        timeout=60
                    )
```

改成：

```python
                    response = requests.post(
                        url=f"{API_BASE}/agent/chat",
                        json={"query": query},
                        timeout=60
                    )
```

- [x] **Step 2: 改 `web_page/rag_direct_page.py`**

把开头改成：

```python
"""web_page/rag_direct_page.py —— 直连 /rag 的简单问答页面（无 Agent 编排）。"""
import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
```

- [x] **Step 3: 改 `web_page/repo_admin.py`**

把第 1~11 行改成：

```python
"""web_page/repo_admin.py —— 仓库管理配置页面（R0：上传文件）。

后续扩展（不在本轮）：
- R1: 文件清单 + 删除按钮
- R2: 单文件重建
- R3: 多知识库切换
"""
import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
```

- [x] **Step 4: 验证三个文件都能 import，且默认值没变**

Run:
```bash
python -c "
import web_page.rag_page as a, web_page.rag_direct_page as b, web_page.repo_admin as c
print(a.API_BASE, b.API_BASE, c.API_BASE)
"
```
Expected: `http://localhost:8000 http://localhost:8000 http://localhost:8000`

- [x] **Step 5: 验证环境变量生效**

Run:
```bash
API_BASE_URL=http://127.0.0.1:9999 python -c "
import web_page.rag_page as a, web_page.rag_direct_page as b, web_page.repo_admin as c
print(a.API_BASE, b.API_BASE, c.API_BASE)
"
```
Expected: `http://127.0.0.1:9999 http://127.0.0.1:9999 http://127.0.0.1:9999`

- [x] **Step 6: 提交（已完成）**

```bash
git add web_page/rag_page.py web_page/rag_direct_page.py web_page/repo_admin.py
git commit -m "feat(web): 前端 API 地址改读 API_BASE_URL（E2E 可测性的前提）"
```

---

## Task 2: `pytest.ini` 加 marker + `test_vector_split.py` 标 slow

> **✅ 已于 2026-11-16「整理 test/ 目录」阶段提前完成**（Step 1–4 全部做完，Step 5 提交按约定暂不执行）。
> 实际落地内容与下述方案一致，只有一处差异：`norecursedirs` 同时排除了 `probes`。

**Files:**
- Modify: `pytest.ini`
- Modify: `test/test_vector_split.py:1-19`

- [x] **Step 1: 改 `pytest.ini`**

改成：

```ini
[pytest]
testpaths = test
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
# test/archive/ 是过时测试脚本的只读归档，test/probes/ 是一次性探针，都不参与收集
norecursedirs = archive probes .* build dist node_modules venv __pycache__
markers =
    slow: 需要真实 Milvus / Ollama / MiniMax —— 慢，且可能花钱
    e2e: 浏览器端到端（Playwright 驱动 Streamlit）
```

- [x] **Step 2: 改 `test/test_vector_split.py`**

在文件头部把 import 段改成：

```python
"""test/test_vector_split.py —— vector_split 端到端测试。

验证：
1. vector_split() 跑通（不再卡在 embed 阶段）
2. txt_data alias 被创建
3. 集合有行数 > 0

前置：Milvus 容器健康、Ollama 在 11434 提供 bge-large embedding。
直接 python test/test_vector_split.py 跑。

⚠️ 标 slow —— 它每次都要把 txt/ 下所有文件重新切分并全量重新 embed
（实测 25 分 29 秒）。默认 pytest 流程不再包含它。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pymilvus import MilvusClient
from utils.txt_spliter.vector_main import vector_split


@pytest.mark.slow
def test_alias_is_created_with_timestamped_collection():
```

（其余函数体不变，只加 `@pytest.mark.slow`。）

- [x] **Step 3: 验证 marker 生效**

Run:
```bash
pytest --collect-only -q 2>&1 | tail -20
```
Expected: 列表里 `test_vector_split.py::test_alias_is_created_with_timestamped_collection` 带 `[slow]`。

- [x] **Step 4: 验证默认流程不再包含它**

Run:
```bash
pytest --collect-only -q -m "not slow and not e2e" 2>&1 | tail -5
```
Expected: 收集数比上一步少 1，且输出里没有 `test_vector_split.py`。

- [x] **Step 5: 提交（已完成）**

```bash
git add pytest.ini test/test_vector_split.py
git commit -m "chore(test): 加 slow/e2e marker，test_vector_split 标 slow"
```

---

## Task 3: `requirements-dev.txt` 加 `pytest-playwright`

**Files:**
- Modify: `requirements-dev.txt`

- [x] **Step 1: 改 `requirements-dev.txt`**

改成：

```text
-r requirements.txt
pytest>=8.0
pytest-cov>=5.0
pytest-playwright>=0.6
```

- [x] **Step 2: 安装**

Run:
```bash
pip install "pytest-playwright>=0.6"
```
Expected: 安装成功。环境里已有 `playwright 1.58.0` + `chromium-1217` 浏览器二进制，**不要**再跑 `playwright install`（会重复下载）。

- [x] **Step 3: 验证插件已加载**

Run:
```bash
pytest --version 2>&1 | head -3
pytest --fixtures 2>&1 | grep -c "^page"
```
Expected: `--version` 输出里含 `playwright`；第二条输出 ≥ 1（`page` fixture 存在）。

- [x] **Step 4: 提交（已完成）**

```bash
git add requirements-dev.txt
git commit -m "chore(dev): 加 pytest-playwright"
```

---

## Task 4: `test/helpers.py`

**Files:**
- Create: `test/helpers.py`

> 本文件是整个 L2 层的地基。所有断言值都来自 2026-11-16 的实跑测量。

- [x] **Step 1: 写 `test/helpers.py`**

```python
"""test/helpers.py —— 测试公共工具（假 LLM / 假检索 / 断言工具）。

为什么需要这一层：
- 假 LLM 要能**按剧本**返回不同角色的内容，还要能记录每次收到的 prompt
  （F1c 的 grounding 断言依赖这个）
- 假检索只替换工具**底下那一层**（_ensure_rag），从而保留 Timer 计时 /
  异常归一化 / status_wrapper 这三段最该被测的真实代码
- 断言工具要能查"悬空 tool_calls"—— v2.2 修过的 bug 的回归护栏
"""
from __future__ import annotations

import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent.runtime import RECURSION_LIMIT

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: Agent 内部占位消息 —— 不该出现在最终答案里
INTERNAL_PLACEHOLDERS = ("READY", "已达迭代上限，结束", "已达总时限，停止思考")

#: 工具返回多段 chunk 时的分隔符（agent/tools/rag_tool.py:64）
CHUNK_SEPARATOR = "\n\n---\n\n"


# ---------------------------------------------------------------------------
# 消息构造
# ---------------------------------------------------------------------------

def tool_call_message(call_id: str, name: str = "rag_search", **args) -> AIMessage:
    """构造一条带 tool_calls 的 AIMessage。

    ⚠️ 每次调用都返回**全新对象** —— LangGraph 的 add_messages 按 message.id
    去重，复用同一个对象会被当成"更新"而不是"新增"。
    """
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {"query": "q"}, "id": call_id}],
    )


def ready_message() -> AIMessage:
    """iter 节点"不调工具"的信号消息。"""
    return AIMessage(content="READY")


# ---------------------------------------------------------------------------
# 假 LLM
# ---------------------------------------------------------------------------

class Script:
    """假 LLM 剧本：每个角色一条出牌列表，**用完后重复最后一项**。

    "重复最后一项"让"恒返回 re_iterate"这类场景一行就能表达。
    列表元素可以是正常返回值，也可以是**要抛出的异常实例**。

    ⚠️ 剧本末尾必须是"停"（如 ready_message()），否则 iter 会一直发工具调用
    直到打满 MAX_ITER —— 那测的就不是你想测的场景了。
    """

    def __init__(self, iter=None, synth=None, reflect=None):
        self.iter = list(iter or [])
        self.synth = list(synth or [])
        self.reflect = list(reflect or [])
        self.calls: list[tuple[str, list]] = []
        self.delays: dict[str, float] = {}
        self._cursor = {"iter": 0, "synth": 0, "reflect": 0}

    def play(self, role: str, messages):
        """按剧本出牌。异常实例会被 raise；消息会返回全新副本。"""
        self.calls.append((role, messages))
        if self.delays.get(role):
            time.sleep(self.delays[role])
        queue = getattr(self, role)
        if not queue:
            raise AssertionError(f"剧本里没有给 {role} 安排返回值")
        index = self._cursor[role]
        item = queue[min(index, len(queue) - 1)]
        self._cursor[role] = index + 1
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, BaseMessage):
            # 全新副本 → 新 id → add_messages 当成"新增"而不是"更新"
            return item.model_copy(update={"id": None})
        return item

    def count(self, role: str) -> int:
        """该角色被调用了几次（= LLM 真实调用次数）。"""
        return sum(1 for r, _ in self.calls if r == role)

    def prompts(self, role: str) -> list[str]:
        """该角色每次收到的 prompt 全文（拼成字符串）。"""
        return [
            "\n".join(str(m.content) for m in messages)
            for r, messages in self.calls if r == role
        ]


class _RoleView:
    """带角色的 chat 视图。

    角色由**调用位置**决定，不靠看 prompt：
    - bind_tools 只有 iter 调
    - with_structured_output 只有 reflect 调
    - 裸 invoke 只有 synth 调
    """

    def __init__(self, script: Script, role: str):
        self._script = script
        self._role = role

    def invoke(self, messages):
        return self._script.play(self._role, messages)


class FakeChat:
    """假的 chat 客户端（替代 ChatOpenAI）。"""

    def __init__(self, script: Script):
        self.script = script

    def invoke(self, messages):                   # synth 路径
        return self.script.play("synth", messages)

    def bind_tools(self, tools):                  # iter 路径
        return _RoleView(self.script, "iter")

    def with_structured_output(self, schema):     # reflect 路径
        return _RoleView(self.script, "reflect")


class FakeLLMInstance:
    """替代 LLMmodel.create_minimax() 的返回值。

    platform / model_name 必须存在 —— ModelManager.add_model 会读它们。
    """

    def __init__(self, script: Script):
        self.script = script
        self.chat = FakeChat(script)
        self.platform = "minimax"
        self.model_name = "MiniMax-M3.1-Flash"


# ---------------------------------------------------------------------------
# 假检索
# ---------------------------------------------------------------------------

class FakeRag:
    """假的 RagModel —— 只实现 retrieve()。

    可配置：返回 chunks / 返回 [] / 抛异常 / 睡 N 秒（配合 TOOL_TIMEOUT 造超时）。
    """

    def __init__(self, chunks=None, error=None, delay=0.0):
        self.chunks = list(chunks or [])
        self.error = error
        self.delay = delay
        self.calls: list[str] = []

    def retrieve(self, query, top_k=5):
        self.calls.append(query)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return list(self.chunks)


# ---------------------------------------------------------------------------
# 断言工具
# ---------------------------------------------------------------------------

def dangling_tool_calls(messages) -> list[str]:
    """找出没有对应 ToolMessage 应答的 tool_call id（"悬空"）。

    悬空 tool_calls 会让 MiniMax 报 HTTP 400（invalid params, tool call and
    result not match）—— v2.2 修过的 bug，这是它的回归护栏。
    """
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    result = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call["id"] not in answered:
                result.append(call["id"])
    return result


def tool_messages(messages) -> list[ToolMessage]:
    """所有 ToolMessage。"""
    return [m for m in messages if isinstance(m, ToolMessage)]


def ai_contents(messages) -> list[str]:
    """所有 AIMessage 的文本内容。"""
    return [m.content for m in messages if isinstance(m, AIMessage)]


def run_graph(graph, question="测试问题", deadline=None, **extra):
    """直接 invoke 图，绕开 runtime.ask() 写死的 90 秒 deadline。

    超时类用例（F9a/F9b/F9c）必须用它 —— ask() 不给控制 deadline 的口子
    （agent/runtime.py:95）。
    """
    state: dict = {"messages": [HumanMessage(content=question)]}
    if deadline is not None:
        state["deadline"] = deadline
    state.update(extra)
    return graph.invoke(state, config={"recursion_limit": RECURSION_LIMIT})
```

- [x] **Step 2: 验证能 import 且不报错**

Run:
```bash
python -c "
from test.helpers import Script, FakeChat, FakeLLMInstance, FakeRag, tool_call_message, dangling_tool_calls
s = Script()
s.iter = [tool_call_message('call_1')]
print('ok', s.count('iter'))
"
```
Expected: `ok 0`（`count` 只统计**已调用**次数，构造时不调用）。

- [x] **Step 3: 验证 `Script.play` 返回的是全新副本**

> ⚠️ 2026-11-16 实跑修正：原计划的断言表达式 `a.id == b.id` 是错的 ——
> `AIMessage.id` 默认就是 `None`，两次比较 `None == None` 恒为 `True`，
> 与"是不是新消息"无关。真正的不变量要**经过 `add_messages`** 才能验证：
> `add_messages` 会给 `id is None` 的消息现场分配 uuid4，所以**同一对象**
> 被返回两次会被折叠成 1 条（第二次被当成"更新"），**全新副本**才会留下 2 条。

Run:
```bash
python -c "
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage
from test.helpers import Script, tool_call_message

def mk():
    return AIMessage(content='', tool_calls=[{'name':'rag_search','args':{'query':'q'},'id':'call_1'}])

shared = mk()
print('A 复用同一对象 ->', len(add_messages(add_messages([], [shared]), [shared])), '条')
s = Script(iter=[tool_call_message('call_1')])
merged = add_messages([], [s.play('iter', []), s.play('iter', [])])
print('B 全新副本     ->', len(merged), '条')
"
```
Expected: `A 复用同一对象 -> 1 条` / `B 全新副本 -> 2 条`

> 这一条是 §0 事实 3 的护栏 —— 如果哪天 `model_copy` 失效，B 会退化成 1 条，
> F1 的 `iter_count` 就会少算一轮。

- [x] **Step 4: 提交（已完成）**

```bash
git add test/helpers.py
git commit -m "feat(test): 新增 test/helpers.py（假 LLM / 假检索 / 断言工具）"
```

---

## Task 5: `test/conftest.py`

**Files:**
- Create: `test/conftest.py`

- [x] **Step 1: 写 `test/conftest.py`**

```python
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
```

- [x] **Step 2: 验证 fixtures 可用（写一个临时用例跑一遍）**

Run:
```bash
cat > /tmp/_t_conftest.py <<'EOF'
from test.helpers import run_graph

def test_smoke(fake_llm, fake_rag, graph):
    fake_rag.chunks = ["片段A"]
    state = run_graph(graph)
    assert state["tool_status"] == {}
EOF
cp /tmp/_t_conftest.py test/_t_conftest.py && pytest test/_t_conftest.py -v; rm -f test/_t_conftest.py
```
Expected: `1 passed`

- [x] **Step 3: 验证 patch 在用例结束后确实还原**

Run:
```bash
cat > test/_t_restore.py <<'EOF'
def test_a_patched(fake_llm):
    from utils.models.model_setting import LLMmodel
    assert isinstance(LLMmodel.__dict__["create_minimax"], staticmethod)

def test_b_restored():
    from utils.models.model_setting import LLMmodel
    assert isinstance(LLMmodel.__dict__["create_minimax"], staticmethod)
EOF
pytest test/_t_restore.py -v; rm -f test/_t_restore.py
```
Expected: `2 passed`（第二个用例证明 patch 已还原且 staticmethod 描述符没丢）

- [x] **Step 4: 提交（已完成）**

```bash
git add test/conftest.py
git commit -m "feat(test): 新增 test/conftest.py（假 LLM / 假检索 / 假后端 / Streamlit fixtures）"
```

---

## Task 6: `test/test_agent_flow.py` — F1 / F1b / F1c / F2

**Files:**
- Create: `test/test_agent_flow.py`

- [x] **Step 1: 写文件骨架 + F1 / F1b / F1c / F2**

```python
"""test/test_agent_flow.py —— L2 · Agent 图的流程测试（核心层）。

跑**真的 LangGraph 图**（不是单测节点），用假 LLM + 假检索控制每一步。
真实保留：节点逻辑 / 条件边路由 / 计数器 reducer / Timer 计时 / 异常归一化 /
status_wrapper 4 态分类 / ToolMessage 写入 / think 剥离。

⚠️ 所有断言值都来自 2026-11-16 的实跑测量，改动断言前先重跑测量。
"""
import json
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from agent.nodes.reflect_node import ReflectOutput
from test.helpers import (
    INTERNAL_PLACEHOLDERS,
    ai_contents,
    dangling_tool_calls,
    ready_message,
    run_graph,
    tool_call_message,
    tool_messages,
)

# reflect 的"通过"决策 —— 大多数用例用它收尾
END = ReflectOutput(is_sufficient=True, critique="", next_action="end")


def test_f1_tool_success_records_ok_status(fake_llm, fake_rag, graph):
    """工具成功 → status=success / code=OK / retryable=false。

    ToolMessage 内容是**拼接后的原文**（rag_tool.py:64 用 "\\n\\n---\\n\\n" 连接），
    不是 chunk 列表，也不做包装。
    """
    fake_rag.chunks = ["片段A", "片段B"]
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="基于片段A的答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    assert state["tool_status"] == {
        "call_1": {
            "tool": "rag_search",
            "status": "success",
            "code": "OK",
            "retryable": False,
        }
    }
    assert tool_messages(state["messages"])[0].content == "片段A\n\n---\n\n片段B"
    assert "基于片段A的答案" in ai_contents(state["messages"])


def test_f1b_two_concurrent_calls_keep_both_statuses(fake_llm, fake_rag, graph):
    """同一轮并发调同一个工具 2 次 → tool_status 的 key 是**调用 id**。

    按工具名做 key 会让后一次调用覆盖前一次的状态（v2.2 修过的 bug）。
    """
    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "rag_search", "args": {"query": "q1"}, "id": "call_a"},
                {"name": "rag_search", "args": {"query": "q2"}, "id": "call_b"},
            ],
        ),
        ready_message(),
    ]
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    assert set(state["tool_status"].keys()) == {"call_a", "call_b"}
    assert all(v["tool"] == "rag_search" for v in state["tool_status"].values())
    assert all(v["status"] == "success" for v in state["tool_status"].values())
    assert len(tool_messages(state["messages"])) == 2


def test_f1c_tool_material_reaches_synth_prompt(fake_llm, fake_rag, graph):
    """grounding：工具结果真的进了综合节点的 prompt。

    没有这一条，F1 的"答案非空"是恒真断言 —— 假 synth 收什么都没关系。
    """
    fake_rag.chunks = ["UNIQUE-CHUNK-ALPHA", "UNIQUE-CHUNK-BETA"]
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [END]

    run_graph(graph)

    prompts = fake_llm.script.prompts("synth")
    assert prompts, "synth 节点没被调用"
    assert "UNIQUE-CHUNK-ALPHA" in prompts[0]
    assert "UNIQUE-CHUNK-BETA" in prompts[0]


def test_f2_empty_result_is_empty_status_with_blank_tool_message(fake_llm, fake_rag, graph):
    """工具返回空 → status=empty / EMPTY_RESULT / retryable=false。

    ToolMessage 内容是**空字符串**（v2.2 的关键修复）—— 不是中文兜底串。
    兜底串会让 status_wrapper 永远判成 success，"检索为空"这个信号就丢了。
    """
    fake_rag.chunks = []
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="没查到")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    entry = state["tool_status"]["call_1"]
    assert entry["status"] == "empty"
    assert entry["code"] == "EMPTY_RESULT"
    assert entry["retryable"] is False
    assert tool_messages(state["messages"])[0].content == ""
```

- [x] **Step 2: 跑这 4 条**

Run:
```bash
pytest test/test_agent_flow.py -v
```
Expected: `4 passed`

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_agent_flow.py
git commit -m "test(agent): L2 流程用例 F1/F1b/F1c/F2"
```

---

## Task 7: `test/test_agent_flow.py` — F3 / F4

**Files:**
- Modify: `test/test_agent_flow.py`（追加两个用例）

- [x] **Step 1: 追加 F3 / F4**

在文件末尾追加：

```python
def test_f3_tool_timeout_is_structured_and_graph_survives(
    fake_llm, fake_rag, graph, monkeypatch
):
    """工具超时 → status=timeout / TOOL_TIMEOUT / retryable=true。

    ToolMessage 内容是**结构化 JSON 载荷**（不是中文散文）；图走完不崩。
    """
    import agent.tools.rag_tool as rag_tool

    # 把 30 秒压到 50 毫秒（rag_tool.py:13 是模块级绑定，:58 是显式传参 → 改绑定即可）
    monkeypatch.setattr(rag_tool, "TOOL_TIMEOUT", 0.05)
    fake_rag.chunks = ["永远读不到"]
    fake_rag.delay = 0.3
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="超时答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    entry = state["tool_status"]["call_1"]
    assert entry["status"] == "timeout"
    assert entry["code"] == "TOOL_TIMEOUT"
    assert entry["retryable"] is True

    payload = json.loads(tool_messages(state["messages"])[0].content)
    assert payload["code"] == "TOOL_TIMEOUT"
    assert payload["status"] == "timeout"
    assert payload["retryable"] is True
    assert "超时" in payload["message"]
    assert "超时答案" in ai_contents(state["messages"])


def test_f4_tool_failure_is_structured_and_graph_survives(fake_llm, fake_rag, graph):
    """工具失败 → status=error / TOOL_ERROR / retryable=false。

    底层 RuntimeError 由 rag_tool 归一化成 AgentToolError，wrapper 再判成 error。
    """
    fake_rag.error = RuntimeError("Milvus 连不上")
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="失败答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    entry = state["tool_status"]["call_1"]
    assert entry["status"] == "error"
    assert entry["code"] == "TOOL_ERROR"
    assert entry["retryable"] is False

    payload = json.loads(tool_messages(state["messages"])[0].content)
    assert payload["code"] == "TOOL_ERROR"
    assert payload["status"] == "error"
    assert payload["retryable"] is False
    assert "Milvus 连不上" in payload["message"]
    assert "失败答案" in ai_contents(state["messages"])
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_agent_flow.py -v
```
Expected: `6 passed`

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_agent_flow.py
git commit -m "test(agent): L2 流程用例 F3（超时）/ F4（失败）"
```

---

## Task 8: `test/test_agent_flow.py` — F5 / F6 / F10 / F11

**Files:**
- Modify: `test/test_agent_flow.py`（追加四个用例）

- [x] **Step 1: 追加 F5 / F6 / F10 / F11**

在文件末尾追加：

```python
def test_f5_iter_llm_crash_falls_back_to_ready(fake_llm, fake_rag, graph):
    """iter 的 LLM 崩 → 兜底 "READY" → synth 仍出答案，图不崩。"""
    fake_llm.script.iter = [RuntimeError("LLM 崩了")]
    fake_llm.script.synth = [AIMessage(content="兜底答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    assert "READY" in ai_contents(state["messages"])
    assert "兜底答案" in ai_contents(state["messages"])
    assert state["tool_status"] == {}
    assert dangling_tool_calls(state["messages"]) == []


def test_f6_reflect_crash_falls_back_to_rewrite(fake_llm, fake_rag, graph):
    """反思解析失败 → critique="反思解析失败"，靠 MAX_REFL 收手。

    ⚠️ 终态 next_action 是 "end" 而不是 "rewrite"：
    兜底 action=rewrite 会再进 synth → 再进 reflect，第 4 次进 reflect 时
    reflection_count 已达 MAX_REFL → 强制 end（reflect_node.py:86-91）。
    """
    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [RuntimeError("反思崩了")]

    state = run_graph(graph)

    assert state["last_critique"] == "反思解析失败"
    assert state["reflection_count"] == 4          # 进了 4 次 reflect
    assert state["next_action"] == "end"           # 第 4 次撞上限强制 end
    assert fake_llm.script.count("reflect") == 3   # 第 4 次不调 LLM
    assert "答案" in ai_contents(state["messages"])


def test_f10_unknown_reflect_action_ends_the_graph(fake_llm, fake_rag, graph):
    """兜底路由分支：reflect 返回未知 action → after_reflect 走 "__end__"。

    ReflectOutput 的 next_action 是 Literal，构造不出 "unknown"，
    所以这里用一个结构相同的普通对象绕过 Pydantic 校验。
    """
    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [
        SimpleNamespace(is_sufficient=False, critique="?", next_action="unknown")
    ]

    state = run_graph(graph)

    assert state["next_action"] == "unknown"
    assert state["reflection_count"] == 1
    assert dangling_tool_calls(state["messages"]) == []


def test_f11_ask_returns_exactly_five_fields(fake_llm, fake_rag, graph):
    """ask(debug=True) 返回**恰好 5 个键**，且答案不是任何内部占位。"""
    from agent.runtime import ask

    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="最终答案")]
    fake_llm.script.reflect = [END]

    result = ask("测试问题", debug=True)

    assert set(result.keys()) == {
        "answer", "iter_count", "reflection_count", "tool_called", "last_action",
    }
    assert result["answer"] == "最终答案"
    assert result["tool_called"] is True
    assert result["last_action"] == "end"
    assert result["answer"] not in INTERNAL_PLACEHOLDERS
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_agent_flow.py -v
```
Expected: `10 passed`

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_agent_flow.py
git commit -m "test(agent): L2 流程用例 F5/F6/F10/F11"
```

---

## Task 9: `test/test_agent_flow.py` — F7 / F8

**Files:**
- Modify: `test/test_agent_flow.py`（追加两个用例）

- [x] **Step 1: 追加 F7 / F8**

在文件末尾追加：

```python
def test_f7_reflect_loop_is_bounded(fake_llm, fake_rag, graph):
    """死循环防护：reflect 恒判 re_iterate → 必须被 MAX_REFL 收住。

    reflect 节点**进入 4 次**，但只有 **3 次 LLM 调用** —— 第 4 次撞
    reflection_count >= MAX_REFL 直接 end，不调 LLM（reflect_node.py:86-91）。
    """
    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [tool_call_message("call_1")]          # 永远发工具调用
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [
        ReflectOutput(is_sufficient=False, critique="再来", next_action="re_iterate")
    ]

    state = run_graph(graph)

    assert state["reflection_count"] == 4
    assert fake_llm.script.count("reflect") == 3     # 第 4 次撞上限，不调 LLM
    assert state["next_action"] == "end"
    assert dangling_tool_calls(state["messages"]) == []


def test_f8_tool_loop_is_bounded_without_dangling_calls(fake_llm, fake_rag, graph):
    """工具循环上限：iter 恒发 tool_calls → iter 节点进 3 次，只调 2 次 LLM。

    第 3 次进 iter 撞 iter_count + 1 >= MAX_ITER，返回"已达迭代上限，结束"，
    **不调 LLM**（iter_node.py:69-73）→ 从根上不产生悬空消息。
    """
    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [tool_call_message("call_1")]
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph)

    assert state["iter_count"] == 3
    assert fake_llm.script.count("iter") == 2      # 第 3 次撞上限，不调 LLM
    assert "已达迭代上限，结束" in ai_contents(state["messages"])
    assert dangling_tool_calls(state["messages"]) == []
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_agent_flow.py -v
```
Expected: `12 passed`

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_agent_flow.py
git commit -m "test(agent): L2 流程用例 F7（反思死循环）/ F8（工具循环上限）"
```

---

## Task 10: `test/test_agent_flow.py` — F9a / F9b / F9c + 公共不变式

**Files:**
- Modify: `test/test_agent_flow.py`（追加四个用例 + 一个参数化用例）

- [x] **Step 1: 追加 F9a / F9b / F9c / F9a 的 xfail + 公共不变式**

在文件末尾追加：

```python
def test_f9a_expired_before_iter_short_circuits(fake_llm, fake_rag, graph):
    """进门即过期 → iter 短路 → should_continue 走 "__end__" → synth 从未执行。"""
    fake_llm.script.iter = [tool_call_message("call_1")]
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [END]

    state = run_graph(graph, deadline=time.time() - 1)

    assert state["expired"] is True
    assert fake_llm.script.count("iter") == 0
    assert fake_llm.script.count("synth") == 0
    assert fake_llm.script.count("reflect") == 0
    assert ai_contents(state["messages"]) == ["已达总时限，停止思考"]


@pytest.mark.xfail(
    strict=True,
    reason="runtime._extract_answer 倒着找最后一条 AIMessage，会把内部占位"
           "「已达总时限，停止思考」当成答案交给用户（项目现状.md §2.8 已记录）",
)
def test_f9a_x_user_should_not_see_internal_placeholder(fake_llm, fake_rag, graph):
    """（期望行为，当前未实现）用户不该看到内部占位消息。

    用 xfail(strict=True) 固化：将来有人修了 _extract_answer，这条会 XPASS →
    报失败 → 逼着摘掉标记。
    """
    from agent.runtime import _extract_answer

    fake_llm.script.iter = [tool_call_message("call_1")]

    state = run_graph(graph, deadline=time.time() - 1)
    answer = _extract_answer(state["messages"])

    assert answer != "已达总时限，停止思考"


def test_f9b_expired_before_synth_returns_timeout_message(fake_llm, fake_rag, graph):
    """synth 前过期 → synth 短路 → 消息是"回答超时：思考时间超过总时限"。

    ⚠️ iter 必须**不发工具调用**：否则工具返回后会再进 iter，
    那次 iter 先撞 is_expired → 消息变成"已达总时限，停止思考"。
    """
    fake_llm.script.iter = [ready_message()]          # 不调工具 → 直接进 synth
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [END]
    fake_llm.script.delays["iter"] = 0.2               # 让 iter 跑完时已过期

    state = run_graph(graph, deadline=time.time() + 0.05)

    assert state["expired"] is True
    assert fake_llm.script.count("synth") == 0         # synth 短路，没调 LLM
    assert fake_llm.script.count("reflect") == 0
    assert ai_contents(state["messages"])[-1] == "回答超时：思考时间超过总时限"


def test_f9c_expired_at_reflect_keeps_synth_answer(fake_llm, fake_rag, graph):
    """reflect 时过期 → 强制 end，但**保留 synth 已写出的答案**。"""
    fake_rag.chunks = ["片段A"]
    fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
    fake_llm.script.synth = [AIMessage(content="正常答案")]
    fake_llm.script.reflect = [END]
    fake_llm.script.delays["synth"] = 0.2

    state = run_graph(graph, deadline=time.time() + 0.05)

    assert state["expired"] is True
    assert state["next_action"] == "end"
    assert state["last_answer"] == "正常答案"
    assert fake_llm.script.count("reflect") == 0       # reflect 短路，没调 LLM
    assert dangling_tool_calls(state["messages"]) == []


# ---------------------------------------------------------------------------
# 公共不变式
# ---------------------------------------------------------------------------

def _setup_scenario(scenario, fake_llm, fake_rag, monkeypatch):
    """按场景名铺好剧本。返回是否需要把工具超时压到 50 毫秒。"""
    fake_llm.script.synth = [AIMessage(content="答案")]
    fake_llm.script.reflect = [END]

    if scenario == "success":
        fake_rag.chunks = ["片段A"]
        fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
        return False
    if scenario == "empty":
        fake_rag.chunks = []
        fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
        return False
    if scenario == "timeout":
        import agent.tools.rag_tool as rag_tool
        monkeypatch.setattr(rag_tool, "TOOL_TIMEOUT", 0.05)
        fake_rag.chunks = ["片段A"]
        fake_rag.delay = 0.3
        fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
        return True
    if scenario == "error":
        fake_rag.error = RuntimeError("Milvus 连不上")
        fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
        return False
    if scenario == "crash_iter":
        fake_llm.script.iter = [RuntimeError("LLM 崩了")]
        return False
    if scenario == "crash_reflect":
        fake_rag.chunks = ["片段A"]
        fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
        fake_llm.script.reflect = [RuntimeError("反思崩了")]
        return False
    if scenario == "loop_reflect":
        fake_rag.chunks = ["片段A"]
        fake_llm.script.iter = [tool_call_message("call_1")]
        fake_llm.script.reflect = [
            ReflectOutput(is_sufficient=False, critique="再来", next_action="re_iterate")
        ]
        return False
    if scenario == "loop_tool":
        fake_rag.chunks = ["片段A"]
        fake_llm.script.iter = [tool_call_message("call_1")]
        return False
    if scenario == "unknown_action":
        fake_rag.chunks = ["片段A"]
        fake_llm.script.iter = [tool_call_message("call_1"), ready_message()]
        fake_llm.script.reflect = [
            SimpleNamespace(is_sufficient=False, critique="?", next_action="unknown")
        ]
        return False
    raise AssertionError(f"未知场景: {scenario}")


@pytest.mark.parametrize(
    "scenario",
    [
        "success", "empty", "timeout", "error",
        "crash_iter", "crash_reflect",
        "loop_reflect", "loop_tool", "unknown_action",
    ],
)
def test_invariant_no_dangling_tool_calls(scenario, fake_llm, fake_rag, graph, monkeypatch):
    """公共不变式：每个 tool_call 都有对应的 ToolMessage —— **悬空数 == 0**。

    悬空 tool_calls 会让 MiniMax 报 HTTP 400（invalid params, tool call and
    result not match）—— 这是 v2.2 修过的 bug，这是它的回归护栏。
    """
    _setup_scenario(scenario, fake_llm, fake_rag, monkeypatch)

    state = run_graph(graph)

    assert dangling_tool_calls(state["messages"]) == []
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_agent_flow.py -v
```
Expected（2026-11-16 实跑修正）：**24 passed, 1 xfailed**（共 25 个收集项）。

拆解：16 个独立用例（F1/F1b/F1c/F2/F3/F4/F5/F6/F7/F8/F9a/F9a_x/F9b/F9c/F10/F11）
+ 9 个参数化实例（公共不变式 × 9 场景）= 25 项，其中 1 项是 xfail。

> 原计划写的"21 passed, 1 xfailed"是算错的（漏数了独立用例）。以实跑为准。
> 若 xfail 用例变成 `XPASS`，pytest 会**报失败** —— 这正是 `strict=True` 的用意。

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_agent_flow.py
git commit -m "test(agent): L2 流程用例 F9a/F9b/F9c + 悬空 tool_calls 公共不变式"
```

---

## Task 11: `test/test_api_contract.py` — C1–C7

**Files:**
- Create: `test/test_api_contract.py`

- [x] **Step 1: 写 `test/test_api_contract.py`**

```python
"""test/test_api_contract.py —— L3 API 契约 + 上传校验。

零外部依赖：TestClient + dependency_overrides，不连 Milvus、不调真 LLM。

⚠️ `from main import app` 必须在**模块顶层**（collection 期）：
main.py:63 在模块级调 LLMmodel.create_minimax()，若在 patch 之后才 import，
假件会变成进程默认模型 → /chat /rag 变成"对着假件测假件"。
"""
from pathlib import Path

import pytest

# ⚠️ 顶层 import —— 见本文件 docstring
from main import app

import api.api_agent as api_agent
import api.api_rag as api_rag
import api.api_file as api_file
from api.dependencies import get_chat_model


@pytest.fixture
def client():
    """FastAPI TestClient。

    ⚠️ 必须用 `with` —— 否则 lifespan 不跑，app.state.model_manager 不存在，
    /chat /rag 的依赖注入会失败。
    """
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def stub_agent(monkeypatch):
    """把 /agent/chat 的 ask 换成固定答案（不打真 LLM）。"""
    monkeypatch.setattr(api_agent, "ask", lambda query, session_id=None: "AGENT 假答案")
    return "AGENT 假答案"


@pytest.fixture
def stub_models():
    """把 /rag 和 /chat 的依赖换成假模型（不连 Milvus、不调真 LLM）。"""

    class FakeRagModel:
        def chat(self, query, session_id):
            return {"response": "RAG 假答案"}

    class FakeChatModel:
        def chat(self, query, session_id):
            return {"response": "CHAT 假答案"}

    app.dependency_overrides[api_rag.get_rag_model] = lambda: FakeRagModel()
    app.dependency_overrides[get_chat_model] = lambda: FakeChatModel()
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def stub_parser(monkeypatch):
    """把 txt_main 换成桩 —— 否则每次上传都会全量扫 documents/ 并解析（慢 + 污染）。"""
    monkeypatch.setattr(api_file, "txt_parse_main", lambda: {"note": "stubbed"})


@pytest.fixture
def restore_model(client):
    """switch_model 改的是**进程全局**模型 —— 测完必须还原。"""
    before = client.get("/current_model").json()
    try:
        yield before
    finally:
        client.post("/switch_model", json=before)


# ---------------------------------------------------------------------------
# C1–C7 · 契约
# ---------------------------------------------------------------------------

def test_c1_agent_chat_returns_response_key(client, stub_agent):
    """/agent/chat 返回 200，body 恰好含 response（不含 answer）。"""
    resp = client.post("/agent/chat", json={"query": "你好"})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"response": "AGENT 假答案"}
    assert "answer" not in body


def test_c2_rag_returns_response_key(client, stub_models):
    """/rag 返回 200，body 含 response。"""
    resp = client.post("/rag", json={"query": "你好"})

    assert resp.status_code == 200
    assert resp.json() == {"response": "RAG 假答案"}


def test_c3_chat_returns_response_key(client, stub_models):
    """/chat 返回 200，body 含 response。"""
    resp = client.post("/chat", json={"query": "你好"})

    assert resp.status_code == 200
    assert resp.json() == {"response": "CHAT 假答案"}


def test_c4_missing_query_is_422_but_empty_query_is_200(client, stub_agent):
    """缺 query 字段 → 422；空串 query → **200**。

    ⚠️ api_agent.py:18 的 Field(...) 没有 min_length —— 空串不是 422。
    """
    missing = client.post("/agent/chat", json={})
    assert missing.status_code == 422

    empty = client.post("/agent/chat", json={"query": ""})
    assert empty.status_code == 200


def test_c5_debug_simple(client):
    """/debug/simple → 200，且能看到 model_manager。"""
    resp = client.get("/debug/simple")

    assert resp.status_code == 200
    assert resp.json()["是否有model_manager"] is True


def test_c6_available_models_contains_minimax(client):
    """/available → 200，列表含 minimax/MiniMax-M3.1-Flash（实测共 11 个模型）。"""
    resp = client.get("/available")

    assert resp.status_code == 200
    models = resp.json()["available_models"]
    assert {"platform": "minimax", "model_name": "MiniMax-M3.1-Flash"} in models


def test_c7_switch_model_success_and_failure(client, restore_model):
    """/switch_model 成功与失败两种响应；测完模型被还原。"""
    ok = client.post(
        "/switch_model",
        json={"platform": "minimax", "model_name": "MiniMax-M3.1-Flash"},
    )
    assert ok.status_code == 200
    assert ok.json()["success"] is True
    assert ok.json()["current_model"] == {
        "platform": "minimax", "model_name": "MiniMax-M3.1-Flash",
    }

    bad = client.post(
        "/switch_model",
        json={"platform": "minimax", "model_name": "不存在的模型"},
    )
    assert bad.status_code == 200
    assert bad.json() == {"success": False, "message": "模型切换失败"}
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_api_contract.py -v
```
Expected: `7 passed`

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_api_contract.py
git commit -m "test(api): L3 API 契约用例 C1–C7"
```

---

## Task 12: `test/test_api_contract.py` — C8–C10（上传校验）

**Files:**
- Modify: `test/test_api_contract.py`（追加三个用例）

- [x] **Step 1: 追加 C8 / C9 / C10**

在文件末尾追加：

```python
# ---------------------------------------------------------------------------
# C8–C10 · 上传校验（后端纯逻辑，零外部依赖）
# ---------------------------------------------------------------------------

def test_c8_path_traversal_is_rejected(client, stub_parser):
    """路径穿越 → 落进 failed_uploads，documents/ 外不产生文件。"""
    resp = client.post(
        "/api/batch-upload-and-parse",
        files=[("files", ("../../evil.txt", b"pwned", "text/plain"))],
    )

    assert resp.status_code == 200
    details = resp.json()["upload_details"]
    assert len(details["failed_uploads"]) == 1
    assert details["failed_uploads"][0]["filename"] == "../../evil.txt"
    assert "非法路径" in details["failed_uploads"][0]["reason"]
    assert details["uploaded_files"] == []
    # documents/ 外没有产生文件
    assert not list(Path("documents").glob("*evil*"))
    assert not list(Path(".").glob("*evil*"))


def test_c9_unsupported_file_type_is_rejected(client, stub_parser):
    """类型白名单 → .exe 落进 failed_uploads。"""
    resp = client.post(
        "/api/batch-upload-and-parse",
        files=[("files", ("bad.exe", b"MZ", "application/octet-stream"))],
    )

    assert resp.status_code == 200
    details = resp.json()["upload_details"]
    assert len(details["failed_uploads"]) == 1
    assert details["failed_uploads"][0]["filename"] == "bad.exe"
    assert "不支持的文件类型" in details["failed_uploads"][0]["reason"]
    assert details["uploaded_files"] == []
    assert not (Path("documents") / "bad.exe").exists()


def test_c10_same_name_is_skipped_unless_overwrite(client, stub_parser):
    """同名文件：默认跳过；overwrite=true 时覆盖。"""
    name = "pytest_probe_upload.txt"
    doc = Path("documents") / name
    if doc.exists():
        doc.unlink()

    try:
        first = client.post(
            "/api/batch-upload-and-parse",
            files=[("files", (name, b"v1", "text/plain"))],
        )
        uploaded = first.json()["upload_details"]["uploaded_files"]
        assert len(uploaded) == 1
        assert uploaded[0]["filename"] == name
        assert uploaded[0]["status"] == "新增"

        second = client.post(
            "/api/batch-upload-and-parse",
            files=[("files", (name, b"v2", "text/plain"))],
        )
        details = second.json()["upload_details"]
        assert details["uploaded_files"] == []
        assert len(details["skipped_files"]) == 1
        assert details["skipped_files"][0]["filename"] == name

        third = client.post(
            "/api/batch-upload-and-parse",
            files=[("files", (name, b"v3", "text/plain"))],
            params={"overwrite": "true"},
        )
        uploaded = third.json()["upload_details"]["uploaded_files"]
        assert len(uploaded) == 1
        assert uploaded[0]["status"] == "覆盖"
    finally:
        if doc.exists():
            doc.unlink()
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_api_contract.py -v
```
Expected: `10 passed`

- [x] **Step 3: 确认没有污染仓库**

Run:
```bash
git status --short documents/ txt/
```
Expected: 无输出（`documents/pytest_probe_upload.txt` 已被用例的 `finally` 清理）

- [x] **Step 4: 提交（已完成）**

```bash
git add test/test_api_contract.py
git commit -m "test(api): L3 上传校验用例 C8–C10（路径穿越 / 类型白名单 / 同名跳过覆盖）"
```

---

## Task 13: `test/test_splitter.py` —— 切分 5 条

**Files:**
- Create: `test/test_splitter.py`

> **为什么要有它**：`test_vector_split.py` 标 slow 之后没人跑 → 摄取链路会腐烂。
> 这 5 条是**纯函数**测试（不 embed、不连 Milvus），永远跑。

- [x] **Step 1: 写 `test/test_splitter.py`**

```python
"""test/test_splitter.py —— 摄取切分的纯函数测试（永远跑）。

不 embed、不连 Milvus、不碰向量库 —— 只测 utils/txt_spliter/spliter.py 的切分逻辑。
补的是 test_vector_split.py 标 slow 之后无人跑的那个洞。

⚠️ 切分器用 chunk_overlap=30 → 相邻块**故意**有 30 个字符的重叠。
所以"拼接结果 == 原文"这种断言是错的（实测会多出重叠部分）。
正确的不变式是：每块都是原文的子串 + 首块以原文开头 + 末块以原文结尾。
"""
import pytest

from utils.txt_spliter.spliter import Splitter

SAMPLE = "这是一段用来测试切分逻辑的中文文本。" * 40 + "结尾标记END"


def test_s1_empty_text_returns_no_chunks():
    """空文本 → 没有块。"""
    assert Splitter().split("") == []


def test_s2_short_text_returns_single_chunk():
    """短文本 → 单块，且原样返回。"""
    chunks = Splitter().split("很短的一段话")

    assert len(chunks) == 1
    assert chunks[0] == "很短的一段话"


def test_s3_chunks_are_non_empty_and_within_limit():
    """每块非空、长度 ≤ 300（LangChain 切分器的 chunk_size）。"""
    chunks = Splitter().split(SAMPLE)

    assert chunks
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_s4_no_content_loss():
    """无内容丢失：每块都是原文子串，首块以原文开头，末块以原文结尾。"""
    chunks = Splitter().split(SAMPLE)

    assert all(chunk in SAMPLE for chunk in chunks)
    assert chunks[0].startswith(SAMPLE[:30])
    assert chunks[-1].endswith(SAMPLE[-30:])


@pytest.mark.xfail(
    strict=True,
    reason="P1-7: max_chars 没传给 LangChain 切分器 —— 代码写死 chunk_size=300，"
           "configs/model_config.yaml 写的是 280（漂移未修）",
)
def test_s5_max_chars_is_honored():
    """（期望行为）Splitter(max_chars=100) 时每块都应 ≤ 100 字符。"""
    chunks = Splitter(max_chars=100).split(SAMPLE)

    assert all(len(chunk) <= 100 for chunk in chunks)
```

- [x] **Step 2: 跑**

Run:
```bash
pytest test/test_splitter.py -v
```
Expected: `4 passed, 1 xfailed`

- [x] **Step 3: 提交（已完成）**

```bash
git add test/test_splitter.py
git commit -m "test(splitter): 切分纯函数用例 5 条（含 P1-7 漂移的 xfail 固化）"
```

---

## Task 14: `test/fake_backend.py` + Streamlit fixture 接通

**Files:**
- Create: `test/fake_backend.py`
- Modify: `test/conftest.py`（`fake_backend` fixture 已在本计划 Task 5 写好，本任务只验证）

- [x] **Step 1: 写 `test/fake_backend.py`**

```python
"""test/fake_backend.py —— 进程外假后端（E2E 用）。

为什么不用 Playwright 的 page.route()：
三个页面的后端调用都发生在 **Streamlit 服务端进程**里
（web_page/rag_page.py:37、web_page/rag_direct_page.py:27、web_page/repo_admin.py:35
的 requests.post），浏览器进程发出的请求根本不经过浏览器 → page.route() 一个都拦不到。
所以必须在进程外起一个真 HTTP 服务，让 Streamlit 通过 API_BASE_URL 指过来。

⚠️ 响应体形状必须**镜像真实契约**（设计文档 §3.5）：
- POST /agent/chat → {"response": ...}
    前端 rag_page.py:44 读 result["response"] → 少这个键会 KeyError → 页面显示"请求失败"
- POST /rag → {"response": ...}
    前端 rag_direct_page.py:33 读 .get("answer") → 返回 response 就落进 P1-1 固化用例
- POST /api/batch-upload-and-parse →
    {"status","message","upload_details":{"uploaded_files","skipped_files","failed_uploads"},
     "parse_results","note"}
    前端 repo_admin.py:44 读 data["upload_details"]["uploaded_files"] → 少这个键会 KeyError
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeBackendState:
    """假后端的可编程状态 —— 用例改这些字段来切换行为。"""

    def __init__(self):
        self.agent_answer = "这是假后端返回的 Agent 答案"
        self.rag_answer = "这是假后端返回的 RAG 答案"
        self.agent_status = 200
        self.rag_status = 200
        self.upload_status = 200
        self.uploaded_count = 1
        self.delay = 0.0
        self.port = 0
        self.requests: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        """静音 —— 假后端不需要刷屏。"""

    @property
    def state(self) -> FakeBackendState:
        return self.server.state

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"status": "ok"})

    def do_POST(self):
        state = self.state
        state.requests.append(self.path)
        self._read_body()
        if state.delay:
            time.sleep(state.delay)

        if self.path == "/agent/chat":
            self._send(state.agent_status, {"response": state.agent_answer})
        elif self.path == "/rag":
            self._send(state.rag_status, {"response": state.rag_answer})
        elif self.path == "/api/batch-upload-and-parse":
            self._send(
                state.upload_status,
                {
                    "status": "completed",
                    "message": (
                        f"批量上传完成：{state.uploaded_count}个成功，0个跳过，0个失败"
                    ),
                    "upload_details": {
                        "uploaded_files": [
                            {
                                "filename": f"probe_{index}.txt",
                                "save_path": f"/tmp/probe_{index}.txt",
                                "status": "新增",
                            }
                            for index in range(state.uploaded_count)
                        ],
                        "skipped_files": [],
                        "failed_uploads": [],
                    },
                    "parse_results": {},
                    "note": "假后端",
                },
            )
        else:
            self._send(404, {"detail": f"未实现的路径: {self.path}"})


def create_server():
    """起一个假后端，返回 (server, state)。端口随机，避开 8000 / 8501 / 8511。"""
    state = FakeBackendState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.state = state
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state
```

- [x] **Step 2: 验证假后端能响应三个端点**

Run:
```bash
python -c "
import json, urllib.request
from test.fake_backend import create_server
server, state = create_server()
base = f'http://127.0.0.1:{state.port}'
for path, payload in [('/agent/chat', {'query': 'x'}), ('/rag', {'query': 'x'}), ('/api/batch-upload-and-parse', {})]:
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as r:
        body = json.loads(r.read())
    print(path, '->', list(body.keys()))
server.shutdown(); server.server_close()
"
```
Expected:
```
/agent/chat -> ['response']
/rag -> ['response']
/api/batch-upload-and-parse -> ['status', 'message', 'upload_details', 'parse_results', 'note']
```

- [x] **Step 3: 验证 Streamlit fixture 能起来**

Run:
```bash
cat > test/_t_streamlit.py <<'EOF'
import pytest
pytestmark = pytest.mark.e2e

def test_streamlit_starts(streamlit_url, fake_backend):
    assert streamlit_url.startswith("http://127.0.0.1:")
    assert fake_backend.port > 0
EOF
pytest test/_t_streamlit.py -v -m e2e; rm -f test/_t_streamlit.py
```
Expected: `1 passed`（首次可能要 10~30 秒等 Streamlit 起来）

- [x] **Step 4: 提交（已完成）**

```bash
git add test/fake_backend.py test/conftest.py
git commit -m "feat(test): 新增进程外假后端（E2E 拦截用）"
```

---

## Task 15: `test/e2e/test_browser_e2e.py` — E1–E7

**Files:**
- Create: `test/e2e/__init__.py`（空文件）
- Create: `test/e2e/test_browser_e2e.py`

- [x] **Step 1: 建 `test/e2e/__init__.py`**

创建空文件 `test/e2e/__init__.py`（让 pytest 按 `test.e2e.test_browser_e2e` 命名模块，
与 `test` 包保持一致，避免 sys.path 冲突）。

- [x] **Step 2: 写 `test/e2e/test_browser_e2e.py`**

```python
"""test/e2e/test_browser_e2e.py —— L4 浏览器 E2E。

跑法：
    pytest -m e2e -v --tracing=retain-on-failure

主体：conftest 起的**进程外假后端** + **专用** Streamlit（8511，注入 API_BASE_URL）。
⚠️ 不复用用户已开的 Streamlit —— 复用来的进程没有 env 注入，拦截会失效。
"""
import time

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

# Streamlit 1.52 的 DOM testid（已在安装包的前端 bundle 里核实存在）
CHAT_INPUT = '[data-testid="stChatInputTextArea"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
CHAT_INPUT_BOX = '[data-testid="stChatInput"]'
UPLOAD_INPUT = '[data-testid="stFileUploaderDropzoneInput"]'
ALERT = '[data-testid="stAlert"]'
HEADING = '[data-testid="stHeading"]'
EXCEPTION = '[data-testid="stException"]'


def open_page(page, url):
    """打开页面并等首屏渲染完。

    Streamlit 要把整个脚本跑完才出内容 —— 首屏超时给到 60 秒。
    """
    page.goto(url, wait_until="domcontentloaded")
    expect(page.locator(CHAT_INPUT)).to_be_visible(timeout=60000)


def menu_frame(page, timeout=30000):
    """拿到 sac.menu 的 frame。

    ⚠️ 菜单渲染在 iframe 里，src 形如 /component/sac.<hash>/index.html
    （streamlit_antd_components 的 _RELEASE=True → 走本地 frontend/build）。
    按 frame.url 匹配，别按包名匹配 —— 包名根本不在 URL 里。
    """
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for frame in page.frames:
            if "/component/sac." in (frame.url or ""):
                return frame
        page.wait_for_timeout(200)
    raise AssertionError("没找到 sac.menu 的 iframe（页面可能没加载完）")


def ask_question(page, text):
    """在聊天框里发一条消息。"""
    box = page.locator(CHAT_INPUT)
    box.fill(text)
    box.press("Enter")


# ---------------------------------------------------------------------------
# E1–E7
# ---------------------------------------------------------------------------

def test_e1_chat_shows_user_and_assistant_messages(page, streamlit_url, fake_backend):
    """智能问答：发问 → 出现用户消息 + 助手答案。"""
    fake_backend.agent_answer = "E1 假后端答案"
    open_page(page, streamlit_url)

    ask_question(page, "你好")

    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)
    expect(page.locator(CHAT_MESSAGE).nth(0)).to_contain_text("你好")
    expect(page.locator(CHAT_MESSAGE).nth(1)).to_contain_text("E1 假后端答案")


def test_e2_clear_button_resets_messages(page, streamlit_url, fake_backend):
    """智能问答：🗑 清空 → 消息归零。"""
    open_page(page, streamlit_url)

    ask_question(page, "你好")
    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)

    page.locator('button:has-text("🗑")').click()

    expect(page.locator(CHAT_MESSAGE)).to_have_count(0, timeout=30000)


def test_e3_settings_button_does_not_crash(page, streamlit_url, fake_backend):
    """智能问答：⚙ 点击不报错（功能未实现，只断言不崩）。"""
    open_page(page, streamlit_url)

    page.locator('button:has-text("⚙")').click()
    page.wait_for_timeout(1500)

    expect(page.locator(EXCEPTION)).to_have_count(0)


@pytest.mark.xfail(
    strict=True,
    reason="P1-1: /rag 前端读 .get('answer')，后端返 'response' → 页面永远显示「(无答案)」",
)
def test_e4_kb_page_shows_no_answer(page, streamlit_url, fake_backend):
    """知识库问答：假后端返回真实契约 {"response": ...} → 页面应显示「(无答案)」。

    ⚠️ 假后端**必须**返回 response 而不是 answer —— 否则这条会意外 XPASS。
    """
    open_page(page, streamlit_url)
    menu_frame(page).get_by_text("知识库问答").click()

    box = page.locator(CHAT_INPUT)
    expect(box).to_be_visible(timeout=60000)
    box.fill("知识库里有什么")
    box.press("Enter")

    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)
    expect(page.locator(CHAT_MESSAGE).nth(1)).to_contain_text("(无答案)")


def test_e5_upload_shows_stats(page, streamlit_url, fake_backend):
    """仓库管理：传文件 → 上传并解析 → 出统计，且数量 > 0。"""
    fake_backend.uploaded_count = 2
    open_page(page, streamlit_url)
    menu_frame(page).get_by_text("仓库管理配置").click()

    expect(page.locator(UPLOAD_INPUT)).to_be_attached(timeout=60000)
    page.locator(UPLOAD_INPUT).set_input_files({
        "name": "probe.txt",
        "mimeType": "text/plain",
        "buffer": b"hello",
    })

    page.locator('button:has-text("上传并解析")').click()

    expect(page.locator(ALERT)).to_contain_text("完成：2 个上传", timeout=60000)


def test_e6_switch_between_three_pages(page, streamlit_url, fake_backend):
    """菜单：三页互切。"""
    open_page(page, streamlit_url)

    menu_frame(page).get_by_text("知识库问答").click()
    expect(page.locator(HEADING)).to_contain_text("知识库问答", timeout=60000)

    menu_frame(page).get_by_text("仓库管理配置").click()
    expect(page.locator(HEADING)).to_contain_text("仓库管理配置", timeout=60000)

    menu_frame(page).get_by_text("智能问答").click()
    expect(page.locator(HEADING)).to_contain_text("智能问答系统", timeout=60000)


def test_e7_backend_500_shows_error_not_blank_page(page, streamlit_url, fake_backend):
    """智能问答：后端返回 500 → 页面显示"请求失败"，不白屏。"""
    fake_backend.agent_status = 500
    open_page(page, streamlit_url)

    ask_question(page, "你好")

    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)
    expect(page.locator(CHAT_MESSAGE).nth(1)).to_contain_text("请求失败")
    expect(page.locator(EXCEPTION)).to_have_count(0)
```

- [x] **Step 3: 跑**

Run:
```bash
pytest -m e2e -v --tracing=retain-on-failure
```
Expected: `6 passed, 1 xfailed`（E4 是 xfail）

> **实测（2026-11-16）**：`7 passed, 1 xfailed in 109.47s`（含 E8 真联调冒烟）。
> 原计划写的 "6 passed" 是按 E1–E7 算的，加了 E8 后是 7。
>
> 落地时踩了三个坑，都已修（**记在这里免得重蹈**）：
> 1. **sac.menu 渲染在 iframe 里**，src 实测是
>    `/component/streamlit_antd_components.utils.component_func.sac/index.html`，
>    **不是**设计文档假设的 `/component/sac.<hash>/index.html` —— 那个模式永远匹配不上。
>    `menu_frame()` 只按 `"/component/" in url and "sac" in url` 两个特征匹配。
> 2. **Streamlit 把每个 `st.button` 渲染两次**（一次在底部固定容器可见、一次在主区隐藏），
>    `button:has-text("🗑")` 会撞 Playwright strict mode → 必须 `.first`。
> 3. **`st.title` / `st.subheader` 都是 `data-testid="stHeading"`**，一页可能不止一个 heading
>    → 断言用 `page.locator(HEADING).first`。
> 4. 假后端的路由匹配必须**先剥掉 query string**（前端会传 `?overwrite=False`），
>    否则 `/api/batch-upload-and-parse` 一律落进 404 分支。

- [x] **Step 4: 若 E4 变成 XPASS，说明假后端返回了错的键**

检查 `test/fake_backend.py` 的 `/rag` 分支是否返回 `{"response": ...}` 而不是 `{"answer": ...}`。

> **实测**：E4 报 **xfailed**（不是 XPASS）—— 假后端 `/rag` 返的确实是 `{"response": ...}`。

- [x] **Step 5: 提交（已完成）**

```bash
git add test/e2e/__init__.py test/e2e/test_browser_e2e.py
git commit -m "test(e2e): 浏览器 E2E 用例 E1–E7（假后端 + 专用 Streamlit）"
```

---

## Task 16: E8 + `test/test_eval_smoke.py` —— S1–S4

**Files:**
- Modify: `test/e2e/test_browser_e2e.py`（追加 E8）
- Create: `test/test_eval_smoke.py`

- [x] **Step 1: 追加 E8（真联调冒烟）**

在 `test/e2e/test_browser_e2e.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# E8 · 真联调冒烟（真后端 + 真 MiniMax）
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_e8_real_backend_smoke(page):
    """真联调：专用 Streamlit 指向**真后端**（8000）+ 真 MiniMax。

    真后端没起 → skip（不硬失败）。CI 里没真环境时这一条会被跳过。
    """
    import os
    import subprocess
    import sys
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/debug/simple", timeout=3) as resp:
            assert resp.status == 200
    except Exception as exc:                       # noqa: BLE001
        pytest.skip(f"真后端未启动（8000）：{exc}")

    port = 8512
    env = os.environ.copy()
    env["API_BASE_URL"] = "http://127.0.0.1:8000"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "main_web.py",
            "--server.port", str(port),
            "--server.address", "127.0.0.1",
            "--server.headless", "true",
        ],
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=3):
                    break
            except Exception:                      # noqa: BLE001
                time.sleep(0.5)
        else:
            pytest.fail("Streamlit 启动超时")

        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        expect(page.locator(CHAT_INPUT)).to_be_visible(timeout=60000)
        ask_question(page, "1+1等于多少")

        expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=120000)
        expect(page.locator(CHAT_MESSAGE).nth(1)).not_to_contain_text("请求失败")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
```

在该文件顶部的 import 区补上 `from pathlib import Path`：

```python
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect
```

- [x] **Step 2: 写 `test/test_eval_smoke.py`**

```python
"""test/test_eval_smoke.py —— L4 真环境冒烟（slow）。

真 MiniMax + 真 Milvus。**默认不跑**（标 slow），跑一次要花钱、也慢。
用途：假 LLM 测不出的东西 —— 真实模型的路由决策、真实检索链路还活着没。

⚠️ S3 已知 flaky：v2.2 实测工具路由准确率 83.3%，失败项是 T06（该检索没检索）。
所以失败时打印实际调了哪个工具，便于人工判断是"回归"还是"LLM 波动"。
"""
import time

import pytest

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def ask():
    """agent.runtime.ask —— 延迟 import，避免慢用例拖慢快回归的收集时间。"""
    from agent.runtime import ask as _ask
    return _ask


def test_s1_calculator_is_called(ask):
    """"1+1等于多少" → tool_called=True，答案含 2。"""
    result = ask("1+1等于多少", debug=True)

    assert result["tool_called"] is True, f"没调工具：{result}"
    assert "2" in result["answer"], f"答案里没有 2：{result['answer']!r}"


def test_s2_greeting_gets_an_answer(ask):
    """"你好" → 答案非空。"""
    result = ask("你好", debug=True)

    assert result["answer"].strip(), f"答案是空的：{result}"
    assert result["answer"] not in ("READY", "已达迭代上限，结束", "已达总时限，停止思考")


def test_s3_knowledge_base_question_uses_rag_search(ask):
    """"我的知识库里有什么内容" → 走 rag_search。

    ⚠️ 这条**天然 flaky**：LLM 有概率不检索（T06 就是这种）。
    失败时打印实际调用的工具名，便于人工判断。
    """
    from langchain_core.messages import HumanMessage

    from agent.runtime import RECURSION_LIMIT, _get_graph

    state = _get_graph().invoke(
        {
            "messages": [HumanMessage(content="我的知识库里有什么内容")],
            "deadline": time.time() + 90,
        },
        config={"recursion_limit": RECURSION_LIMIT},
    )

    tools = sorted({v.get("tool") for v in (state.get("tool_status") or {}).values()})
    print(f"[S3] 实际调用的工具: {tools}")
    assert "rag_search" in tools, f"没走 rag_search，实际调了：{tools}"


def test_s4_tool_failure_does_not_run_away(ask):
    """工具失败后，reflect 不该把图带进死循环。

    做法：把 rag_search 底下那层换成会抛异常的假件，**LLM 保持真**，
    看图能不能收手。

    ⚠️ 天然 flaky（LLM 决策随机）→ 只断言"不失控"，不断言具体 next_action。
    """
    from unittest.mock import patch

    from test.helpers import FakeRag

    with patch(
        "agent.tools.rag_tool._ensure_rag",
        lambda: FakeRag(error=RuntimeError("冒烟测试故意制造的失败")),
    ):
        result = ask("我的知识库里有什么内容", debug=True)

    print(f"[S4] result={result}")
    assert result["reflection_count"] <= 4, f"反思次数失控：{result}"
    assert result["answer"].strip(), f"答案是空的：{result}"
```

- [x] **Step 3: 跑慢用例（需真后端环境）**

Run:
```bash
pytest -m slow -v
```
Expected: S1–S4 全部通过（或 S3 因 LLM 波动失败 —— 属已知 flaky）
`test_vector_split.py` 也在 slow 里，会跑 25 分钟 —— 想跳过它就：
```bash
pytest -m slow -v --deselect test/test_vector_split.py
```

> **实测（2026-11-16）**：`pytest -m slow -v --deselect test/test_vector_split.py`
> → **5 passed in 162.38s**。
> ⚠️ 选了 **5** 个不是 4 个 —— **E8 同时带 `slow` 和 `e2e` 两个标记**，
> 所以 `-m slow` 也会选它（`-m` 是"或"语义，不是"且"）。
> S3（已知 flaky）这次也过了。

- [x] **Step 4: 提交（已完成）**

```bash
git add test/e2e/test_browser_e2e.py test/test_eval_smoke.py
git commit -m "test(smoke): 真环境冒烟用例 S1–S4 + 浏览器真联调 E8"
```

---

## Task 17: 文档同步 + 全量验收

**Files:**
- Modify: `docs/plan/2026-11-16-test-suite-design.md`（修 §4.1 F6 的断言口径 —— Δ1）
- Modify: `docs/status/测试体系.md`（§5 落地状态全部改成 ✅，补实测结果）
- Modify: `docs/status/项目现状.md`（§0 测试行 + P0-2 状态）
- Modify: `test/README.md`（新增文件索引）
- Modify: `CLAUDE.md`（测试文件清单 + 跑法）

- [x] **Step 1: 修设计文档 F6 的断言口径**

在 `docs/plan/2026-11-16-test-suite-design.md` 的 §4.1 表格里，把 F6 那一行：

```
| F6 | 反思解析失败 | 假 reflect 抛异常 | `next_action=rewrite` + `last_critique="反思解析失败"`；不崩 |
```

改成：

```
| F6 | 反思解析失败 | 假 reflect 抛异常 | `last_critique="反思解析失败"`；`reflection_count=4`；**终态 `next_action="end"`**（第 4 次进 reflect 撞 `MAX_REFL` 强制 end，不调 LLM）；reflect LLM 只调 3 次；不崩 |
```

同时在 §11 的自审记录里追加一条：

```
| **D-26** | F6 的断言 `next_action=rewrite` 与实测不符 | 实测终态是 `end`：兜底 action=rewrite 会再进 synth → 再进 reflect，第 4 次进 reflect 时 `reflection_count` 已达 `MAX_REFL` → 强制 end（`reflect_node.py:86-91`） | F6 改为断言 `last_critique` / `reflection_count=4` / 终态 `next_action="end"` / reflect LLM 3 次 |
```

- [x] **Step 2: 更新 `docs/status/测试体系.md` 的落地状态**

把 §5「落地状态追踪」表里 12 项的 🔴 全部改成 ✅，并在表下方追加一节实测结果：

```markdown
### 落地结果（2026-11-16 实测）

| 命令 | 结果 |
|---|---|
| `pytest -m "not slow and not e2e" -v` | **XX passed, 1 xfailed**，耗时 YY 秒 |
| `pytest -m e2e -v --tracing=retain-on-failure` | **6 passed, 1 xfailed** |
| `pytest -m slow -v --deselect test/test_vector_split.py` | **4 passed**（S3 偶发 flaky） |
```

> 跑完把实际数字填进去，别抄这里的占位。

- [x] **Step 3: 更新 `docs/status/项目现状.md`**

- §0 摘要表的测试行改成实测口径：

```
| 测试 | 4 层测试体系**已落地**（38 条）→ [`status/测试体系.md`](./测试体系.md) |
```

- §8 的 P0-2 条目状态从"未做"改成"已做"，并注明：Agent 图的路由逻辑已有 11 条 pytest 覆盖（`test/test_agent_flow.py`），公共不变式"悬空 tool_calls == 0"已固化为参数化回归网。

- [x] **Step 4: 更新 `test/README.md`**

在 §一 的分类表里加一行：

```
| **I · 新增测试层** | `test_agent_flow.py`（11）<br>`test_api_contract.py`（10）<br>`test_splitter.py`（5）<br>`test_eval_smoke.py`（4，slow）<br>`e2e/test_browser_e2e.py`（8，e2e） | ✅ 收集 | 2026-11-16 建的 4 层测试体系，详见 [`../docs/status/测试体系.md`](../docs/status/测试体系.md) |
```

并把 §四「这些测试没有覆盖什么」的第 1、2 条改掉 —— Agent 图零覆盖这个洞已经补上了：

```
1. **reflect prompt 的"工具失败时不判 re_iterate"硬约束** —— 假 reflect 被剧本编排，原理上测不到；
   只有 S4（真 LLM）能覆盖，且天然 flaky。这是本轮**明确不覆盖**的部分。
2. **评估集口径过时** —— 二值 `expected_tool` vs v2.2 的 4 个工具（见上）。
```

- [x] **Step 5: 更新 `CLAUDE.md` 的测试段**

把 "Currently live test files:" 那段改成：

```markdown
Currently live test files:

- `test/test_agent_timeout.py` — timeout/exception mechanism (11 cases, no Milvus or LLM needed).
- `test/test_main_routes_covered.py` — AST scan of `api/*.py` + `main.py`, prevents unmounted router dead code (2 cases).
- `test/test_agent_flow.py` — **L2 Agent flow layer**: runs the real LangGraph graph with a fake LLM (scripted) and a fake retriever. Covers tool success/empty/timeout/error, LLM crashes, both loop guards, the three timeout timings, and the `ask()` contract (11 cases + a parametrized "no dangling tool_calls" invariant).
- `test/test_api_contract.py` — **L3 API contract layer**: `TestClient` + `dependency_overrides`. Field shapes, missing-field 422, model switching, and the upload validation logic (path traversal / type whitelist / same-name skip-or-overwrite) (10 cases).
- `test/test_splitter.py` — pure-function splitter checks (5 cases, always run).
- `test/test_vector_split.py` — end-to-end `vector_split()`; **marked `slow`** (measured: 25 min 29 s).
- `test/test_eval_smoke.py` — real MiniMax + real Milvus smoke (**marked `slow`**).
- `test/e2e/test_browser_e2e.py` — Playwright against a **process-external fake backend** + a dedicated Streamlit on port 8511 (**marked `e2e`**).

The four-layer system is documented in `docs/status/测试体系.md`; its design is
`docs/plan/2026-11-16-test-suite-design.md`.
```

并把跑法段改成：

```bash
# Fast regression (seconds; no browser, no real LLM)
pytest -m "not slow and not e2e" -v

# Browser E2E (keeps trace/video on failure)
pytest -m e2e -v --tracing=retain-on-failure

# Real-environment smoke (slow, costs money)
pytest -m slow -v

# Everything
pytest -v
```

- [x] **Step 6: 全量验收**

Run:
```bash
pytest -m "not slow and not e2e" -v
```
Expected: **全绿**，且总耗时 **< 60 秒**（实测 `import main` 就要 5.1 秒、`import agent.runtime` 3.5 秒 —— 预算是 60 秒不是 30 秒）
→ ✅ **51 passed, 2 xfailed, 13 deselected in 9.70s**

Run:
```bash
pytest -m e2e -v --tracing=retain-on-failure
```
Expected: **全绿**（E4 报 `xfailed` 属正常）
→ ✅ **7 passed, 1 xfailed in 109.47s**

Run:
```bash
pytest -v
```
Expected: 全部收集到，无 collection error
→ ⚠️ **62 passed, 3 xfailed, 1 failed in 2005.53s（33:25）** —— 唯一失败是 `test_vector_split.py`，
  **不是产品缺陷**：Milvus `insert()` 是异步落盘的（返回只代表 WAL 收下，segment 还没 flush），
  所以 `insert → create_index → load_collection → alter_alias` 走完的**瞬间** `query()` 可能还返回 0 行
  （1667 行时命中；3 行对照实验延迟为 0）。**数据一条没丢**（`count(*)` = 1667）。
  修法：**只在测试侧**把断言改成轮询（`test/test_vector_split.py::_wait_for_rows`，最多 180 秒），
  产品代码 `utils/txt_spliter/vector_main.py` 一行没动。
  复验：`pytest test/test_vector_split.py -v` → ✅ **1 passed in 1792.13s（29:52）**。

- [x] **Step 7: 确认没有污染仓库**

Run:
```bash
git status --short
```
Expected: 只有计划内的改动（`documents/`、`txt/` 干净）
→ ✅ `git status --short documents/ txt/` **无输出**；全量 `git status --short` 只有计划内的改动
  （新测试文件 + 文档 + 前端 `API_BASE_URL` 三处；`test/test_vector_split.py` 是本步唯一的额外改动）。

- [x] **Step 8: 提交（已完成）**

```bash
git add -A docs/status docs/plan test README.md CLAUDE.md
git commit -m "docs(test): 同步测试体系落地状态与实跑结果"
```

---

## §3 验收标准对照（设计文档 §8）

| # | 标准 | 在哪个 Task 验证 | 通过判据 |
|---|---|---|---|
| A1 | `pytest -m "not slow and not e2e"` 全绿，< 60 秒 | Task 17 Step 6 | 全绿 + 计时 < 60s |
| A2 | `pytest -m e2e` 全绿（E4 报 xfailed 属正常） | Task 17 Step 6 | `7 passed, 1 xfailed` |
| A3 | F3 / F4 能复现"超时/失败时会发生什么" | Task 7 | 状态字段 + JSON 载荷 + 图终止 + 最终答案，四个都断言 |
| A4 | 公共不变式在 F1–F10 全部成立 | Task 10 | 9 个场景参数化，悬空数全为 0 |
| A5 | 现有 13 个用例不回归 | Task 17 Step 6 | `test_agent_timeout.py` + `test_main_routes_covered.py` 全绿 |
| A6 | `pytest` 默认不再跑 25 分钟的 `test_vector_split.py` | Task 2 | `pytest -m "not slow and not e2e"` 的收集列表里没有它 |
| A7 | F1c 成立（chunk 文本出现在 synth 的 prompt 里） | Task 6 | 两个 UNIQUE-CHUNK 断言 |
| A8 | 干净 clone 上按 §7 的命令能跑通 | Task 17 Step 6（本地） | 全量命令可跑；CI 留待后续 |

---

## §4 明确不做（与设计文档 §1.3 一致）

| 项 | 原因 |
|---|---|
| 改 `agent/` 业务代码 | 本轮只写测试。发现的 bug 用 `xfail(strict=True)` 固化（F9a 的占位消息、P1-7 的 max_chars 漂移） |
| 修 P1-1（`/rag` 前端读 `answer`） | 用 E4 的 `xfail(strict=True)` 固化，等用户另行拍板 |
| 测 reflect prompt 的"工具失败时不判 re_iterate"硬约束 | 假 reflect 被剧本编排，原理上测不到 → 只有 S4（真 LLM）能覆盖且天然 flaky |
| L0 白盒单测（reducer 内部、prompt 文本断言） | 计数器语义改从图的外层观测点断言 |
| CI workflow | 仓库无 CI 平台配置；本轮保证"本地一条命令能跑" |
| 视觉回归截图对比 | —— |
| 测未实现的功能（⚙ 模型配置按钮、`session_id` 多轮记忆） | E3 只断言"点了不崩" |
| 重写 `test/archive/scripts/` 的 8 个归档脚本 | 它们是历史参照，不是回归网 |

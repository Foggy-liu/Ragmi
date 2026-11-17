"""test/test_agent_timeout.py —— 超时与异常机制的回归测试。

覆盖 4 种工具状态（success / empty / timeout / error）+ 计时器 +
图级 deadline 判定 + FastAPI 端点不阻塞事件循环的守护。

不连 Milvus、不调真实 LLM：工具执行是假的，只测"状态分类"这一层逻辑。
"""
from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from agent.errors import AgentTimeoutError, AgentToolError
from agent.nodes.status_tool_wrapper import status_wrapper
from agent.timeout import Timer, is_expired

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _FakeRequest:
    """模拟 ToolCallRequest —— status_wrapper 只用到 .tool_call 这一个属性。"""

    def __init__(self, name: str = "rag_search", call_id: str = "call_1"):
        self.tool_call = {"name": name, "args": {}, "id": call_id}


def _status(cmd: Command) -> dict:
    """取出 Command 里的 tool_status 字典。"""
    return cmd.update["tool_status"]


def _entry(tool: str, status: str, code: str, retryable: bool) -> dict:
    """tool_status 里某次调用的 value（结构化条目）。"""
    return {"tool": tool, "status": status, "code": code, "retryable": retryable}


# ===== 工具状态 4 条分支 =====

def test_tool_status_success():
    """工具返回非空内容 → success。"""

    def execute(request):
        return ToolMessage(content="检索到的资料", tool_call_id="call_1", name="rag_search")

    cmd = status_wrapper(_FakeRequest(), execute)

    assert _status(cmd) == {"call_1": _entry("rag_search", "success", "OK", False)}
    assert cmd.update["messages"][0].content == "检索到的资料"


def test_tool_status_empty():
    """工具返回空内容 → empty（不是 success —— "检索为空"这个信号要能传出去）。"""

    def execute(request):
        return ToolMessage(content="", tool_call_id="call_1", name="rag_search")

    cmd = status_wrapper(_FakeRequest(), execute)

    assert _status(cmd) == {"call_1": _entry("rag_search", "empty", "EMPTY_RESULT", False)}


def test_tool_status_timeout():
    """工具超时 → timeout，并且必须回写 ToolMessage。

    漏写 ToolMessage 的后果：graph 停在"有 tool_calls 但没应答"的状态，
    下一步 LLM 会收到非法消息序列（MiniMax 直接报 400）。
    """

    def execute(request):
        raise AgentTimeoutError("调用超过 30s 未返回")

    cmd = status_wrapper(_FakeRequest(), execute)

    assert _status(cmd) == {"call_1": _entry("rag_search", "timeout", "TOOL_TIMEOUT", True)}

    msg = cmd.update["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "call_1"
    assert msg.name == "rag_search"

    # 失败载荷是结构化 JSON（不是中文散文）——LLM 能明确读出 code/retryable
    payload = json.loads(msg.content)
    assert payload["code"] == "TOOL_TIMEOUT"
    assert payload["status"] == "timeout"
    assert payload["retryable"] is True
    assert "调用超时" in payload["message"]


def test_tool_status_error():
    """工具非超时失败 → error（不可重试）。"""

    def execute(request):
        raise AgentToolError("检索失败: ConnectError")

    cmd = status_wrapper(_FakeRequest(), execute)

    assert _status(cmd) == {"call_1": _entry("rag_search", "error", "TOOL_ERROR", False)}
    assert isinstance(cmd.update["messages"][0], ToolMessage)

    payload = json.loads(cmd.update["messages"][0].content)
    assert payload["code"] == "TOOL_ERROR"
    assert payload["retryable"] is False


# ===== 计时器 + 图级 deadline =====

def test_timer_turns_slow_call_into_agent_timeout():
    """Timer 给同步调用套时间上限：超时抛 AgentTimeoutError，不抛裸 TimeoutError。"""

    def slow():
        time.sleep(2)
        return "never"

    with pytest.raises(AgentTimeoutError):
        Timer(timeout=0.2).call(slow)


def test_timer_passes_through_normal_result():
    """正常返回时 Timer 不改变结果。"""
    assert Timer(timeout=5).call(lambda x: x + 1, 41) == 42


def test_is_expired_uses_deadline():
    """deadline 是绝对时间戳：过期=真，没设 deadline=不过期。"""
    assert is_expired({"deadline": time.time() + 10}) is False
    assert is_expired({"deadline": time.time() - 1}) is True
    assert is_expired({}) is False


# ===== 超时兜底：交出上一次的答案 =====

def test_synth_expired_returns_previous_answer():
    """超时时把上一次 synth 写出的答案交出去（比干巴巴一句"超时"有用）。

    回归点：早前版本从 messages 里倒着找"最后一条不带 tool_calls 的 AIMessage"，
    但 iter 节点的占位消息（"READY"）也不带 tool_calls → 占位消息被当成答案交出去。
    改用 state["last_answer"] 之后才正确。
    """
    from agent.nodes.synth_node import synth_node

    state = {
        "messages": [HumanMessage("问题")],
        "deadline": time.time() - 1,        # 已过期
        "last_answer": "上一次写好的答案",
        "last_critique": "",
    }
    out = synth_node(state)

    assert out["messages"][0].content == "上一次写好的答案"
    assert out["expired"] is True


def test_synth_expired_without_previous_answer():
    """第一次就超时、没有任何旧答案 → 明确说超时，不留空。"""
    from agent.nodes.synth_node import synth_node

    state = {
        "messages": [HumanMessage("问题")],
        "deadline": time.time() - 1,
        "last_answer": "",
    }
    out = synth_node(state)

    assert out["messages"][0].content == "回答超时：思考时间超过总时限"
    assert out["expired"] is True


def test_expired_state_routes_to_end():
    """expired=True 时两个条件边都直接 END，不再迭代/重写。"""
    from agent.nodes.should_continue import after_reflect, should_continue

    state = {"expired": True, "messages": [], "iter_count": 0, "next_action": "rewrite"}

    assert should_continue(state) == "__end__"
    assert after_reflect(state) == "__end__"


# ===== FastAPI 端点守护 =====

def test_agent_chat_endpoint_is_not_async():
    """agent_chat 必须是 def，不是 async def。

    agent.runtime.ask() 是同步阻塞的（LLM HTTP + 工具检索 + 线程等待），
    写在 async def 里会占住事件循环 → 一个慢请求把整个服务卡死。
    FastAPI 对普通 def 路由会自动丢到线程池执行。

    用 AST 静态检查，不 import 业务模块（避免触发 Milvus / LLM 副作用）。
    """
    src = (PROJECT_ROOT / "api" / "api_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "agent_chat":
            assert not isinstance(node, ast.AsyncFunctionDef), (
                "api_agent.agent_chat 不能是 async def —— 同步阻塞调用会占住事件循环"
            )
            return

    pytest.fail("api/api_agent.py 里找不到 agent_chat 函数")

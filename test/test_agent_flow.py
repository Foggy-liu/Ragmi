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


def test_f9a_x_user_should_not_see_internal_placeholder(fake_llm, fake_rag, graph):
    """用户不该看到 iter 的内部占位消息。

    修复前 runtime._extract_answer 倒着找最后一条 AIMessage，图超时时会把
    「已达总时限，停止思考」当成答案交出去（项目现状.md §2.8）。
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

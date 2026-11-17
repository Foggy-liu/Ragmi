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
    from agent.constants import INTERNAL_SIGNALS

    result = ask("你好", debug=True)

    assert result["answer"].strip(), f"答案是空的：{result}"
    # 从 agent.constants 导入而不是复制一份字面量 —— 复制就会漂移，
    # 这条断言会变成永真（agent 侧新增内部信号时测试侧不会跟着更新）。
    assert result["answer"] not in INTERNAL_SIGNALS


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

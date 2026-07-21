"""test/test_reflection_count.py —— 实测 reflection_count 边界行为。

这是 M3 Task 3.0 决策任务：测 reflect_node 在 MAX_REFL 边界的行为对不对。
用 MockLLM 替代真实 LLM（不依赖 .env / 网络），断言两个场景：

场景 1: count=0 初始 → 应调 LLM，pass=False（mock 返回 insufficient），
        返回 {"reflection_count": 1, "last_reflection_pass": False}
场景 2: count=1=MAX_REFL → 应短路（不调 LLM），pass=True（兜底强制通过），
        返回 {"reflection_count": 1, "last_reflection_pass": True}

如果两个都符合 → 行为正确，无须改 agent/state.py，继续 M3。
直接 python test/test_reflection_count.py 跑。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage, AIMessage
from agent.nodes import reflect as reflect_mod
from agent.state import AgentState, MAX_REFL


class MockLLM:
    def __init__(self, content):
        self.content = content
        self.invoke_calls = []

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        from langchain_core.messages import AIMessage as _AIM
        return _AIM(content=self.content)


def scenario_1_count_zero():
    """count=0 应调 LLM, pass=False（mock 返回 insufficient）。"""
    mock = MockLLM('{"is_sufficient": false, "critique": "需要更多信息"}')
    reflect_mod._llm = mock

    state = {
        "messages": [HumanMessage(content="q"), AIMessage(content="a")],
        "reflection_count": 0,
    }
    result = reflect_mod.reflect_node(state)

    assert mock.invoke_calls, "应至少调 LLM 一次"
    assert result["last_reflection_pass"] is False, f"pass 应是 False，实际 {result['last_reflection_pass']}"
    assert result["reflection_count"] == 1, f"应返回增量 1，实际 {result['reflection_count']}"
    print(f"[scenario 1 OK] LLM 被调 {len(mock.invoke_calls)} 次, pass=False, 返回 count=1")


def scenario_2_count_max():
    """count=MAX_REFL=1 应短路（不调 LLM），pass=True。"""
    mock = MockLLM('{"is_sufficient": true, "critique": "ok"}')  # 即使 mock 说通过也不调它
    reflect_mod._llm = mock

    state = {
        "messages": [HumanMessage(content="q"), AIMessage(content="a")],
        "reflection_count": MAX_REFL,  # 等于 1
    }
    result = reflect_mod.reflect_node(state)

    assert len(mock.invoke_calls) == 0, f"短路时应不调 LLM，实际调了 {len(mock.invoke_calls)} 次"
    assert result["last_reflection_pass"] is True, f"短路 pass 应是 True，实际 {result['last_reflection_pass']}"
    assert result["reflection_count"] == 1, f"短路应返回增量 1，实际 {result['reflection_count']}"
    print(f"[scenario 2 OK] LLM 0 次调用, pass=True (兜底), 返回 count=1")


if __name__ == "__main__":
    print(f"MAX_REFL = {MAX_REFL}")
    print(f"AgentState fields: {list(AgentState.__annotations__.keys())}")
    print()

    scenario_1_count_zero()
    scenario_2_count_max()
    print("\n两个场景都符合预期，MAX_REFL 边界行为正确。继续 M3。")

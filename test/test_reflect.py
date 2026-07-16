"""test/test_reflect.py —— parse_reflection_json 纯逻辑单元测试。

不需要 pytest，直接 python test/test_reflect.py 跑。
TDD: 先写失败测试，下一任务实现。
"""
import sys
from pathlib import Path

# 让 test/ 目录能 import agent/
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.nodes.reflect import parse_reflection_json  # 这一步会失败, 因为还没实现
from langchain_core.messages import HumanMessage, AIMessage


def test_valid_json_passes():
    """标准 JSON 输入应被解析。"""
    text = '{"is_sufficient": true, "critique": ""}'
    result = parse_reflection_json(text)
    assert result == {"is_sufficient": True, "critique": ""}, f"got {result}"


def test_json_with_surrounding_text():
    """LLM 在 JSON 前后加废话，应能容错提取。"""
    text = '好的，我的评判是：{"is_sufficient": false, "critique": "信息不全"} 以上。'
    result = parse_reflection_json(text)
    assert result["is_sufficient"] is False
    assert "信息不全" in result["critique"]


def test_garbage_falls_back_to_insufficient():
    """完全乱码应触发 fail-safe 默认 insufficient。"""
    text = "我无法评判这个答案。"
    result = parse_reflection_json(text)
    assert result["is_sufficient"] is False
    assert "解析失败" in result["critique"]


def test_partial_json_falls_back():
    """截断的 JSON（缺右括号）应触发 fail-safe。"""
    text = '{"is_sufficient": true, "critique":'
    result = parse_reflection_json(text)
    assert result["is_sufficient"] is False


def test_missing_is_sufficient_defaults_to_false():
    """JSON 缺 is_sufficient 字段应默认 False（fail-safe）。"""
    text = '{"critique": "something"}'
    result = parse_reflection_json(text)
    # 即使 JSON 能解析, is_sufficient 缺失也要 fail-safe
    assert result["is_sufficient"] is False


def test_is_sufficient_string_false():
    """LLM 偶尔返回字符串 'false' 而非 JSON false, 应正确解析为 False。"""
    text = '{"is_sufficient": "false", "critique": ""}'
    result = parse_reflection_json(text)
    assert result["is_sufficient"] is False


# ===== reflect_node 测试（mock LLM） =====

class MockLLM:
    """模拟 LLM，固定返回指定内容。"""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.invoke_calls = []

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        return _MockAIMessage(self.response_text)


class _MockAIMessage:
    def __init__(self, content):
        self.content = content


def _make_state(messages: list, reflection_count: int = 0) -> dict:
    """构造最小可用 state。"""
    return {
        "messages": messages,
        "reflection_count": reflection_count,
        "iterations": 1,
    }


def test_reflect_node_passes_when_sufficient(monkeypatch=None):
    """LLM 判 sufficient 时, last_reflection_pass=True, 不追加 critique AIMessage。"""
    from agent.nodes import reflect as reflect_mod

    mock = MockLLM('{"is_sufficient": true, "critique": ""}')
    reflect_mod._llm = mock  # 替换单例

    state = _make_state(
        [
            HumanMessage(content="什么是 ReAct 模式？"),
            AIMessage(content="ReAct 是一种推理+行动的模式..."),
        ]
    )

    result = reflect_mod.reflect_node(state)

    assert result["last_reflection_pass"] is True
    assert result["reflection_count"] == 1
    # 不追加 critique AIMessage
    assert "messages" not in result or len(result.get("messages", [])) == 0
    print("  ✓ test_reflect_node_passes_when_sufficient")


def test_reflect_node_fails_appends_critique():
    """LLM 判 insufficient 时, 追加 critique AIMessage, last_reflection_pass=False。"""
    from agent.nodes import reflect as reflect_mod

    mock = MockLLM('{"is_sufficient": false, "critique": "信息不全, 应提到 A 和 B"}')
    reflect_mod._llm = mock

    state = _make_state(
        [
            HumanMessage(content="list 和 tuple 的区别？"),
            AIMessage(content="list 是可变序列。"),  # 不全
        ]
    )

    result = reflect_mod.reflect_node(state)

    assert result["last_reflection_pass"] is False
    assert result["reflection_count"] == 1
    # 追加 critique AIMessage
    assert len(result.get("messages", [])) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert "信息不全" in result["messages"][0].content
    print("  ✓ test_reflect_node_fails_appends_critique")


def test_reflect_node_force_pass_when_max_reached():
    """reflection_count >= MAX_REFL 时强制 pass (兜底)。"""
    from agent.nodes import reflect as reflect_mod

    mock = MockLLM('{"is_sufficient": false, "critique": "再反思"}')
    reflect_mod._llm = mock

    state = _make_state(
        [
            HumanMessage(content="q"),
            AIMessage(content="a"),
        ],
        reflection_count=1,  # 等于 MAX_REFL
    )

    result = reflect_mod.reflect_node(state)

    # 即使 LLM 说不通过, MAX_REFL 兜底强制 pass
    assert result["last_reflection_pass"] is True
    print("  ✓ test_reflect_node_force_pass_when_max_reached")


def test_reflect_node_handles_garbage_output():
    """LLM 返回乱码时, 触发 fail-safe 默认 insufficient。"""
    from agent.nodes import reflect as reflect_mod

    mock = MockLLM("我无法评判")  # 完全无法解析
    reflect_mod._llm = mock

    state = _make_state(
        [
            HumanMessage(content="q"),
            AIMessage(content="a"),
        ]
    )

    result = reflect_mod.reflect_node(state)

    assert result["last_reflection_pass"] is False
    assert "messages" in result and len(result["messages"]) == 1
    print("  ✓ test_reflect_node_handles_garbage_output")


def main():
    tests = [
        test_valid_json_passes,
        test_json_with_surrounding_text,
        test_garbage_falls_back_to_insufficient,
        test_partial_json_falls_back,
        test_missing_is_sufficient_defaults_to_false,
        test_is_sufficient_string_false,  # T4 fix added this
        test_reflect_node_passes_when_sufficient,
        test_reflect_node_fails_appends_critique,
        test_reflect_node_force_pass_when_max_reached,
        test_reflect_node_handles_garbage_output,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{len(tests)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

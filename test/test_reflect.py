"""test/test_reflect.py —— parse_reflection_json 纯逻辑单元测试。

不需要 pytest，直接 python test/test_reflect.py 跑。
TDD: 先写失败测试，下一任务实现。
"""
import sys
from pathlib import Path

# 让 test/ 目录能 import agent/
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.nodes.reflect import parse_reflection_json  # 这一步会失败, 因为还没实现


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


def main():
    tests = [
        test_valid_json_passes,
        test_json_with_surrounding_text,
        test_garbage_falls_back_to_insufficient,
        test_partial_json_falls_back,
        test_missing_is_sufficient_defaults_to_false,
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

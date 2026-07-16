"""agent/nodes/reflect.py —— 答案质量评估节点（v2.1）。

节点职责：
1. 读 state.messages，提取 question + answer
2. 调 LLM（REFLECT_PROMPT）做三维度评判
3. 解析 JSON 输出（带容错）
4. 写回 state: reflection_count +1, last_reflection_pass, [可选] critique AIMessage
"""
import json
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.prompts.reflect_prompt import REFLECT_PROMPT
from agent.state import MAX_REFL


def _to_bool(v) -> bool:
    """安全布尔转换：处理 LLM 返回字符串 'false' 而非 JSON false 的情况。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def parse_reflection_json(text: str) -> dict:
    """解析反思节点的 JSON 输出。失败时 fail-safe 默认 insufficient。

    三层容错：
    1. json.loads 完整解析
    2. 正则提取 {...} 子串再解析
    3. 终极 fail-safe: 返回 insufficient + 默认 critique
    """
    # 1. 直接 JSON 解析
    try:
        result = json.loads(text)
        if "is_sufficient" in result:
            return {
                "is_sufficient": _to_bool(result["is_sufficient"]),
                "critique": str(result.get("critique", "")),
            }
    except (json.JSONDecodeError, ValueError, TypeError):
        # JSON 解析失败是预期内的边界情况，继续尝试正则 fallback
        pass

    # 2. 正则 fallback
    m = re.search(r"\{[^{}]*\"is_sufficient\"[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group())
            return {
                "is_sufficient": _to_bool(result.get("is_sufficient", False)),
                "critique": str(result.get("critique", "")),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            # 正则提取的子串仍无法解析，继续尝试终极 fail-safe
            pass

    # 3. 终极 fail-safe
    return {"is_sufficient": False, "critique": "(反思输出解析失败, 默认重答)"}

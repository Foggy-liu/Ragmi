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
                "is_sufficient": bool(result["is_sufficient"]),
                "critique": str(result.get("critique", "")),
            }
    except Exception:
        pass

    # 2. 正则 fallback
    m = re.search(r"\{[^{}]*\"is_sufficient\"[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group())
            return {
                "is_sufficient": bool(result.get("is_sufficient", False)),
                "critique": str(result.get("critique", "")),
            }
        except Exception:
            pass

    # 3. 终极 fail-safe
    return {"is_sufficient": False, "critique": "(反思输出解析失败, 默认重答)"}

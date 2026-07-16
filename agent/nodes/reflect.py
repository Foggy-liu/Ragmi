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


# ===== reflect_node =====

_llm = None


def _get_llm():
    """懒加载反思 LLM（与 agent 同 MiniMax-M3, 30s 超时）。"""
    global _llm
    if _llm is None:
        from utils.models.model_setting import LLMmodel

        llm_instance = LLMmodel.create_minimax("MiniMax-M3")
        _llm = llm_instance.chat.with_config({"timeout": 30})
    return _llm


def reflect_node(state: dict) -> dict:
    """反思节点：评答案质量，决定走 END 还是回 agent 重答。

    输入：state dict (含 messages, reflection_count)
    输出：
        {
          "reflection_count": 1,
          "last_reflection_pass": bool,
          "messages": [...]   # 仅当 fail 时追加 critique AIMessage
        }
    """
    # 0. 超限保护（双保险）—— 必须在 LLM 初始化之前短路，避免浪费初始化与消息解析
    current_count = state.get("reflection_count", 0)
    if current_count >= MAX_REFL:
        # 强制通过，避免无限循环
        return {
            "reflection_count": 1,
            "last_reflection_pass": True,
        }

    # 1. 拿 LLM（测试里会 mock 成 MockLLM）
    llm = _get_llm()

    # 2. 拿 question 和 answer
    messages_list = state["messages"]
    question = messages_list[0].content
    answer = messages_list[-1].content

    # 3. 调 LLM 评判
    prompt_messages = [
        SystemMessage(content=REFLECT_PROMPT),
        HumanMessage(content=f"问题：{question}\n\n答案：{answer}"),
    ]
    response = llm.invoke(prompt_messages)

    # 4. 解析 JSON
    result = parse_reflection_json(response.content)
    is_sufficient = bool(result.get("is_sufficient", False))
    critique = result.get("critique", "")

    # 5. 构造返回值
    update = {
        "reflection_count": 1,
        "last_reflection_pass": is_sufficient,
    }

    # 6. 不通过且有 critique 时，追加 AIMessage 触发重答
    if not is_sufficient and critique:
        update["messages"] = [AIMessage(content=f"反思意见：{critique}")]

    return update

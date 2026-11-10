"""agent/nodes/reflect_node.py —— v2.2 反思节点。

v2.2 变化（vs v2.1）：
- 用 Pydantic ReflectOutput 解析（替代正则 + JSON 三层 fallback）
- 输出 next_action 字段（end / rewrite / re_iterate）
- 失败 fallback：next_action = rewrite（reflection_count 上限兜底防死循环）
- reflection_count >= MAX_REFL → 强制 next_action = end
- rewrite / re_iterate 时重置 iter_count + synth_count = 0

think 剥离：通过 ThinkingStripRunnable 包装 LLM，invoke 返回的 AIMessage.content
自动剥掉 ``<think>...</think>`` 块（推理模型污染防护，让 Pydantic 能解析 JSON）。
"""
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from agent.constants import MAX_REFL
from agent.llm_wrapper import ThinkingStripRunnable
from agent.prompts.reflect_prompt import REFLECT_PROMPT
from agent.state import AgentState


class ReflectOutput(BaseModel):
    """Structured output for reflect node。

    Fields:
        is_sufficient: 答案是否通过评审。
        critique: 若 insufficient 写修改方向；否则留空。
        next_action: end (通过) / rewrite (synth 重写) / re_iterate (回 iter)。
    """
    is_sufficient: bool
    critique: str = ""
    next_action: Literal["end", "rewrite", "re_iterate"]


def _get_llm():
    """懒加载反思 LLM（with_structured_output, 30s 超时 + 剥 think）。"""
    from utils.models.model_setting import LLMmodel

    llm_instance = LLMmodel.create_minimax("MiniMax-M3.1-Flash")
    return ThinkingStripRunnable(
        llm_instance.chat
        .with_structured_output(ReflectOutput)
        .with_config({"timeout": 30})
    )


def _extract_latest_answer(messages: list) -> str:
    """从 messages 中提取最后一条 AIMessage 的内容。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content or ""
    return ""


def reflect_node(state: AgentState, llm=None) -> dict:
    """反思节点：评答案质量，决定 next_action。

    Args:
        state: AgentState
        llm: 可选注入的 LLM（测试用）；None 时懒加载真实 LLM

    Returns:
        dict 含 "reflection_count" 增量、"next_action"、"last_critique"，
        以及（rewrite/re_iterate 时）"iter_count" 和 "synth_count" 重置。
    """
    reflection_count = state.get("reflection_count") or 0

    # 边界：反思超限强制 end（兜底防死循环）
    if reflection_count >= MAX_REFL:
        return {
            "reflection_count": 1,
            "next_action": "end",
            "last_critique": state.get("last_critique", ""),
        }

    if llm is None:
        llm = _get_llm()

    # 构造 prompt
    question = state["messages"][0].content if state["messages"] else ""
    latest_answer = _extract_latest_answer(state["messages"])
    tool_status = state.get("tool_status", {})

    prompt_messages = [
        SystemMessage(content=REFLECT_PROMPT),
        HumanMessage(content=(
            f"【用户问题】\n{question}\n\n"
            f"【本次答案】\n{latest_answer}\n\n"
            f"【工具状态】\n{tool_status}\n\n"
            f"【历史反思】（本次会话内）\n{state.get('last_critique', '')}\n"
        )),
    ]

    # LLM 调用 + Pydantic 解析（带异常兜底）
    try:
        parsed = llm.invoke(prompt_messages)
        # Pydantic 模型 → dict
        action = parsed.next_action
        critique = parsed.critique
    except Exception:
        # LLM 失败 / Pydantic 解析失败 → 兜底 rewrite（reflection_count 上限兜底防死循环）
        action = "rewrite"
        critique = "反思解析失败"

    result = {
        "reflection_count": 1,
        "next_action": action,
        "last_critique": critique,
    }

    # rewrite / re_iterate 时重置 iter_count + synth_count
    if action != "end":
        result["iter_count"] = 0
        result["synth_count"] = 0

    return result
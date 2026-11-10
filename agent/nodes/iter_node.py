"""agent/nodes/iter_node.py —— v2.2 纯决策节点。

职责：决定"要不要调工具"。不调工具时输出 "READY" 信号让 synth 节点写答案。

边界检查：iter_count >= MAX_ITER → 强制 END。
LLM 异常兜底：try/except 包裹 llm.invoke()，失败时返回 READY 信号（不写答案）。

think 剥离：通过 ThinkingStripRunnable 包装 LLM，invoke 返回的 AIMessage.content
自动剥掉 ``<think>...</think>`` 块（推理模型污染防护）。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.constants import MAX_ITER
from agent.llm_wrapper import ThinkingStripRunnable
from agent.prompts.iter_prompt import ITER_PROMPT
from agent.state import AgentState
from agent.tools import ALL_TOOLS


def _get_llm():
    """懒加载 LLM（已 bind_tools(ALL_TOOLS), 30s 超时 + 剥 think）。"""
    from utils.models.model_setting import LLMmodel

    llm_instance = LLMmodel.create_minimax("MiniMax-M3.1-Flash")
    return ThinkingStripRunnable(
        llm_instance.chat
        .bind_tools(ALL_TOOLS)
        .with_config({"timeout": 30})
    )


def iter_node(state: AgentState, llm=None) -> dict:
    """iter 决策节点。

    Args:
        state: AgentState
        llm: 可选注入的 LLM（测试用）；None 时懒加载真实 LLM

    Returns:
        dict 含 "messages" (单条 AIMessage) 和 "iter_count" 增量
    """
    iter_count = state.get("iter_count") or 0

    # 边界：迭代上限强制输出提示（让 should_continue → synth → reflect → END）
    if iter_count >= MAX_ITER:
        return {
            "messages": [AIMessage(content="已达迭代上限，结束")],
            "iter_count": 1,  # 仍递增（让超限事件被记录）
        }

    if llm is None:
        llm = _get_llm()

    # 构造 prompt
    question = state["messages"][0].content if state["messages"] else ""
    prompt_messages = [
        SystemMessage(content=ITER_PROMPT),
        HumanMessage(content=(
            f"【用户问题】\n{question}\n\n"
            f"【当前状态】\n"
            f"- iter_count: {iter_count}\n"
            f"- tool_status: {state.get('tool_status', {})}\n"
            f"- 反思反馈（reflect 触发 re_iterate 时才有）: {state.get('last_critique', '')}\n"
        )),
    ]

    # LLM 调用（带异常兜底）
    try:
        response = llm.invoke(prompt_messages)
    except Exception:
        # 兜底：LLM 失败时返回 READY 信号（让 synth 节点写兜底答案）
        response = AIMessage(content="READY")

    return {
        "messages": [response],
        "iter_count": 1,
    }
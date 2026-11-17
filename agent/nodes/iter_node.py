"""agent/nodes/iter_node.py —— v2.2 纯决策节点。

职责：决定"要不要调工具"。不调工具时输出 "READY" 信号让 synth 节点写答案。

边界检查：iter_count >= MAX_ITER → 强制 END。
LLM 异常兜底：try/except 包裹 llm.invoke()，失败时返回 READY 信号（不写答案）。

think 剥离：通过 ThinkingStripRunnable 包装 LLM，invoke 返回的 AIMessage.content
自动剥掉 ``<think>...</think>`` 块（推理模型污染防护）。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.constants import (
    LLM_TIMEOUT,
    MAX_ITER,
    SIGNAL_EXPIRED,
    SIGNAL_MAX_ITER,
    SIGNAL_READY,
)
from agent.llm_wrapper import ThinkingStripRunnable
from agent.nodes.material import collect_round_material
from agent.nodes.status_tool_wrapper import format_tool_status
from agent.prompts.iter_prompt import ITER_PROMPT
from agent.state import AgentState
from agent.timeout import is_expired
from agent.tools import ALL_TOOLS


def _get_llm():
    """懒加载 LLM（已 bind_tools(ALL_TOOLS), LLM_TIMEOUT 超时 + 剥 think）。

    超时用 ChatOpenAI 构造参数（timeout=），不是 .with_config({"timeout": N}）
    —— 后者 langchain_core 从不读 RunnableConfig["timeout"]，是无效代码。
    """
    from utils.models.model_setting import LLMmodel

    llm_instance = LLMmodel.create_minimax("MiniMax-M3.1-Flash", timeout=LLM_TIMEOUT)
    return ThinkingStripRunnable(
        llm_instance.chat
        .bind_tools(ALL_TOOLS)
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

    # 图级总时限检查：已超时就不再调 LLM，直接收摊
    if is_expired(state):
        return {
            "messages": [AIMessage(content=SIGNAL_EXPIRED)],
            "expired": True,
            "iter_count": 1,
        }

    # 边界：迭代上限强制输出提示（让 should_continue → synth → reflect → END）
    #
    # 为什么用 iter_count + 1 而不是 iter_count：
    # iter_count 是"已经跑过几次"（上一次调用累加后的值），本次调用之后才会
    # 变成 MAX_ITER。写成 iter_count >= MAX_ITER 时，第 MAX_ITER 次进入本节点
    # 时 iter_count 还是 MAX_ITER-1 → 不触发边界 → 白调一次 LLM →
    # LLM 发出的 tool_calls 会被 should_continue 直接丢弃（它先判 iter_count
    # 上限再判 tool_calls）→ 留下一条"有 tool_calls 但没有 ToolMessage"的
    # AIMessage（悬空）。MiniMax 收到这种消息序列会报 400
    # （invalid params, tool call and result not match）。
    # 提前一轮收手，从根上不产生悬空；顺带省掉一次白跑的 LLM 调用。
    if iter_count + 1 >= MAX_ITER:
        return {
            "messages": [AIMessage(content=SIGNAL_MAX_ITER)],
            "iter_count": 1,  # 仍递增（让超限事件被记录）
        }

    if llm is None:
        llm = _get_llm()

    # 构造 prompt
    question = state["messages"][0].content if state["messages"] else ""
    material = collect_round_material(state["messages"])
    prompt_messages = [
        SystemMessage(content=ITER_PROMPT),
        HumanMessage(content=(
            f"【用户问题】\n{question}\n\n"
            f"【本轮工具素材】（如果有——上一轮查到的资料）\n{material or '（无）'}\n\n"
            f"【当前状态】\n"
            f"- iter_count: {iter_count}\n"
            f"- 反思反馈（reflect 触发 re_iterate 时才有）: {state.get('last_critique', '')}\n\n"
            f"【工具状态】\n{format_tool_status(state.get('tool_status', {}))}\n"
        )),
    ]

    # LLM 调用（带异常兜底）
    try:
        response = llm.invoke(prompt_messages)
    except Exception:
        # 兜底：LLM 失败时返回 READY 信号（让 synth 节点写兜底答案）
        response = AIMessage(content=SIGNAL_READY)

    return {
        "messages": [response],
        "iter_count": 1,
    }
"""agent/nodes/synth_node.py —— v2.2 综合节点。

单一节点处理"首次写答案"和"重写答案"两种模式：
- 首次：state["last_critique"] 为空 → 基于素材写答案
- 重写：state["last_critique"] 非空 → 基于素材 + critique 改写

不调工具（v2.1 节点双角色 bug 修复点）。

think 剥离：通过 ThinkingStripRunnable 包装 LLM，invoke 返回的 AIMessage.content
自动剥掉 ``<think>...</think>`` 块（推理模型污染防护，避免污染 state.messages）。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.constants import MAX_SYNTH
from agent.llm_wrapper import ThinkingStripRunnable
from agent.prompts.synth_prompt import SYNTH_PROMPT
from agent.state import AgentState


def _get_llm():
    """懒加载 LLM（不挂 bind_tools，30s 超时 + 剥 think）。"""
    from utils.models.model_setting import LLMmodel

    llm_instance = LLMmodel.create_minimax("MiniMax-M3.1-Flash")
    return ThinkingStripRunnable(
        llm_instance.chat.with_config({"timeout": 30})
    )


def _format_tool_status(tool_status: dict) -> str:
    """把 tool_status dict 格式化为可读字符串。"""
    if not tool_status:
        return "（无工具调用）"
    lines = [f"- {name}: {status}" for name, status in tool_status.items()]
    return "\n".join(lines)


def synth_node(state: AgentState, llm=None) -> dict:
    """综合节点：写最终答案。

    Args:
        state: AgentState
        llm: 可选注入的 LLM（测试用）；None 时懒加载真实 LLM

    Returns:
        dict 含 "messages" (单条 AIMessage) 和 "synth_count" 增量 + "last_critique" 透传
    """
    synth_count = state.get("synth_count") or 0

    # 边界：综合上限强制输出提示
    if synth_count >= MAX_SYNTH:
        return {
            "messages": [AIMessage(content="已达综合上限，结束")],
            "synth_count": 1,
            "last_critique": state.get("last_critique", ""),
        }

    if llm is None:
        llm = _get_llm()

    # 构造 prompt
    question = state["messages"][0].content if state["messages"] else ""
    tool_status = state.get("tool_status", {})
    last_critique = state.get("last_critique", "")

    # 提取素材：从 messages 中找最近的 ToolMessage 内容
    chunks_text = ""
    for msg in reversed(state["messages"]):
        # ToolMessage 是 LangChain 标准类，有 content 属性
        if msg.__class__.__name__ == "ToolMessage" and getattr(msg, "content", ""):
            chunks_text = msg.content
            break

    prompt_messages = [
        SystemMessage(content=SYNTH_PROMPT),
        HumanMessage(content=(
            f"【用户问题】\n{question}\n\n"
            f"【可用素材】（如果有）\n{chunks_text}\n\n"
            f"【工具状态】\n{_format_tool_status(tool_status)}\n\n"
            f"【反思反馈】（如果有——重写模式才有）\n{last_critique}\n"
        )),
    ]

    # LLM 调用（带异常兜底）
    try:
        response = llm.invoke(prompt_messages)
    except Exception as e:
        response = AIMessage(content=f"综合答案生成失败：{type(e).__name__}")

    return {
        "messages": [response],
        "synth_count": 1,
        "last_critique": last_critique,  # 透传（reflect 下次会更新）
    }
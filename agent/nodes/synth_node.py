"""agent/nodes/synth_node.py —— v2.2 综合节点。

单一节点处理"首次写答案"和"重写答案"两种模式：
- 首次：state["last_critique"] 为空 → 基于素材写答案
- 重写：state["last_critique"] 非空 → 基于素材 + critique 改写

不调工具（v2.1 节点双角色 bug 修复点）。

think 剥离：通过 ThinkingStripRunnable 包装 LLM，invoke 返回的 AIMessage.content
自动剥掉 ``<think>...</think>`` 块（推理模型污染防护，避免污染 state.messages）。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.constants import LLM_TIMEOUT
from agent.llm_wrapper import ThinkingStripRunnable
from agent.nodes.material import collect_round_material
from agent.nodes.status_tool_wrapper import format_tool_status
from agent.prompts.synth_prompt import SYNTH_PROMPT
from agent.state import AgentState
from agent.timeout import is_expired


def _get_llm():
    """懒加载 LLM（不挂 bind_tools，LLM_TIMEOUT 超时 + 剥 think）。

    超时用 ChatOpenAI 构造参数（timeout=），不是 .with_config({"timeout": N}）
    —— 后者 langchain_core 从不读 RunnableConfig["timeout"]，是无效代码。
    """
    from utils.models.model_setting import LLMmodel

    llm_instance = LLMmodel.create_minimax("MiniMax-M3.1-Flash", timeout=LLM_TIMEOUT)
    return ThinkingStripRunnable(llm_instance.chat)


def synth_node(state: AgentState, llm=None) -> dict:
    """综合节点：写最终答案。

    Args:
        state: AgentState
        llm: 可选注入的 LLM（测试用）；None 时懒加载真实 LLM

    Returns:
        dict 含 "messages" (单条 AIMessage) 和 "last_critique" 透传
    """
    # 图级总时限检查：超时时把「上一次的答案」交给用户，
    # 比干巴巴一句"超时"有用得多（放在 _get_llm() 之前，避免白加载一次 LLM）
    if is_expired(state):
        prev = (state.get("last_answer") or "").strip()
        return {
            "messages": [AIMessage(content=prev or "回答超时：思考时间超过总时限")],
            "last_critique": state.get("last_critique", ""),
            "last_answer": prev,
            "expired": True,
        }

    if llm is None:
        llm = _get_llm()

    # 构造 prompt
    question = state["messages"][0].content if state["messages"] else ""
    tool_status = state.get("tool_status", {})
    last_critique = state.get("last_critique", "")

    # 提取素材：本轮（最后一条 HumanMessage 之后）的全部 ToolMessage
    chunks_text = collect_round_material(state["messages"])

    prompt_messages = [
        SystemMessage(content=SYNTH_PROMPT),
        HumanMessage(content=(
            f"【用户问题】\n{question}\n\n"
            f"【可用素材】（如果有——本轮查到的全部资料）\n{chunks_text or '（无）'}\n\n"
            f"【工具状态】\n{format_tool_status(tool_status)}\n\n"
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
        "last_critique": last_critique,  # 透传（reflect 下次会更新）
        "last_answer": (response.content or "").strip(),
    }
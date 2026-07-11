"""agent/nodes/agent.py —— Agent 决策节点（LangGraph 图的核心节点之一）。

节点职责：
1. 读 state["messages"]
2. 注入 SYSTEM_PROMPT 作为第一条消息
3. 调 LLM（已 bind_tools）
4. 返回新 AIMessage（框架按 add_messages 规则追加到 state）

本节点每次执行都调一次 LLM。LLM 的 AIMessage 可能含 tool_calls（要调工具）
或纯文本回答（直接输出）。
"""

from langchain_core.messages import SystemMessage

from agent.prompts.system_prompt import SYSTEM_PROMPT
from agent.tools.rag_tool import rag_search
from utils.models.model_setting import LLMmodel


_llm = None


def _get_llm():
    """懒加载 LLM 单例（已 bind_tools = [rag_search]）。"""
    global _llm
    if _llm is None:
        llm_instance = LLMmodel.create_minimax()
        _llm = llm_instance.chat.bind_tools([rag_search])
    return _llm


def agent_node(state: dict) -> dict:
    """Agent 决策节点。

    输入：state dict（含 messages）
    输出：{"messages": [AIMessage]} — 框架按 add_messages 自动追加

    边方向：节点输出含 tool_calls 时走 should_continue → ToolNode；
            否则直接 END。
    """
    llm = _get_llm()

    # 系统 prompt 作为第一条消息注入（每次调用都带，模型侧会缓存）
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])

    # 调 LLM，拿到 AIMessage（含 tool_calls 或纯文本）
    response = llm.invoke(messages)

    # 返回增量（框架自动 merge 到 state.messages）
    return {"messages": [response]}

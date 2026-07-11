"""agent/nodes/should_continue.py —— 条件边路由函数。

LangGraph 用这个函数决定 agent_node 之后下一步去哪：
- AIMessage 含 tool_calls → 走 "tools"（执行工具）
- 否则 → "__end__"（完成）
"""


def should_continue(state: dict) -> str:
    """条件边函数。判断 AIMessage 是否含 tool_calls。

    输入：state dict（含 messages）
    输出："tools" 或 "__end__"
    """
    last_message = state["messages"][-1]

    # AIMessage 有 tool_calls 属性（list），非空说明 LLM 想调工具
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "__end__"

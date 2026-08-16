"""agent/nodes/status_tool_node.py —— StatusToolNode (v2.2)。

包装 LangGraph ToolNode，捕获工具执行状态写入 state["tool_status"] 字典。
4 种 status 值：
- success: 工具返回非空内容
- empty: 工具返回空字符串（无超时）
- timeout: 工具抛 TimeoutError
- error: 工具抛其他异常

兜底：timeout/error 时仍写 ToolMessage（避免 graph 卡住）。
"""
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from agent.state import AgentState


class StatusToolNode(ToolNode):
    """包装 LangGraph ToolNode，捕获异常写 tool_status 字典。"""

    def __init__(self, tools: list):
        super().__init__(tools)

    def __call__(self, state: AgentState) -> dict:
        # 取最后一个 AIMessage 的 tool_calls
        last_msg = state["messages"][-1]
        if not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
            return {}  # 没有 tool_calls 不应到这（兜底）

        tool_call = last_msg.tool_calls[0]
        tool_name = tool_call["name"]
        tool_call_id = tool_call["id"]

        try:
            result = super().__call__(state)
            # ToolNode 返回 {"messages": [ToolMessage, ...]}
            tool_msgs = result.get("messages", [])
            has_content = any(getattr(m, "content", "") for m in tool_msgs)
            status = "success" if has_content else "empty"
            return {
                **result,
                "tool_status": {tool_name: status},
            }
        except TimeoutError:
            # 兜底：写 ToolMessage 占位（避免 graph 卡在 tool_calls 未应答）
            return {
                "messages": [ToolMessage(
                    content="查询超时",
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )],
                "tool_status": {tool_name: "timeout"},
            }
        except Exception:
            return {
                "messages": [ToolMessage(
                    content="工具异常",
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )],
                "tool_status": {tool_name: "error"},
            }
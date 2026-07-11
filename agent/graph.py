"""agent/graph.py —— LangGraph 图装配。

把节点、工具、条件边拼成可执行图：
- 入口 → agent → (条件路由) → tools → agent → ...
- 或 agent → END
"""

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.nodes.agent import agent_node
from agent.nodes.should_continue import should_continue
from agent.state import AgentState
from agent.tools.rag_tool import rag_search


def build_graph():
    """构造 + 编译 LangGraph 图，返回可 invoke 的对象。"""
    # LangGraph 自带的 ToolNode：自动执行 tool_call、把 ToolMessage 回写到 state
    tool_node = ToolNode([rag_search])

    workflow = StateGraph(AgentState)

    # 节点
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    # 入口
    workflow.set_entry_point("agent")

    # 条件边：从 agent 出来，看 should_continue 决定去哪
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "__end__": END,
        },
    )

    # 工具执行完再回到 agent 决策（ReAct 循环的核心）
    workflow.add_edge("tools", "agent")

    return workflow.compile()

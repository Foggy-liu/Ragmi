"""agent/graph.py —— LangGraph 图装配 (v2.1)。

节点：agent / tools / reflect
边：
  agent → {tools, reflect, __end__}       (should_continue)
  tools → agent
  reflect → {agent, __end__}              (after_reflect)
"""

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.nodes.agent import agent_node
from agent.nodes.reflect import reflect_node
from agent.nodes.should_continue import after_reflect, should_continue
from agent.state import AgentState
from agent.tools.rag_tool import rag_search


def build_graph():
    """构造 + 编译 LangGraph 图，返回可 invoke 的对象。"""
    tool_node = ToolNode([rag_search])

    workflow = StateGraph(AgentState)

    # 节点
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("reflect", reflect_node)

    # 入口
    workflow.set_entry_point("agent")

    # 第一个条件边：agent → {tools, reflect, END}
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "reflect": "reflect",
            "__end__": END,
        },
    )

    # 工具执行完回到 agent（ReAct 循环核心）
    workflow.add_edge("tools", "agent")

    # 第二个条件边：reflect → {agent, END}
    workflow.add_conditional_edges(
        "reflect",
        after_reflect,
        {
            "agent": "agent",
            "__end__": END,
        },
    )

    return workflow.compile()

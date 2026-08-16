"""agent/graph.py —— LangGraph 图装配 (v2.2)。

4 节点：iter / tools / synth / reflect
边：
  START → iter (无条件)
  iter → {tools, synth} (should_continue)
  tools → iter (无条件)
  synth → reflect (无条件)
  reflect → {END, synth, iter} (after_reflect)
"""
from langgraph.graph import END, StateGraph

from agent.nodes.iter_node import iter_node
from agent.nodes.reflect_node import reflect_node
from agent.nodes.should_continue import after_reflect, should_continue
from agent.nodes.status_tool_node import StatusToolNode
from agent.nodes.synth_node import synth_node
from agent.state import AgentState
from agent.tools import ALL_TOOLS


def build_graph():
    """构造 + 编译 LangGraph 图，返回可 invoke 的对象。"""
    tool_node = StatusToolNode(ALL_TOOLS)

    workflow = StateGraph(AgentState)

    # 4 节点
    workflow.add_node("iter", iter_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("synth", synth_node)
    workflow.add_node("reflect", reflect_node)

    # 入口
    workflow.set_entry_point("iter")

    # 第一个条件边：iter → {tools, synth}
    workflow.add_conditional_edges(
        "iter",
        should_continue,
        {
            "tools": "tools",
            "synth": "synth",
        },
    )

    # tools → iter（ReAct 循环核心）
    workflow.add_edge("tools", "iter")

    # synth → reflect（无条件）
    workflow.add_edge("synth", "reflect")

    # 第二个条件边：reflect → {END, synth, iter}
    # path_map 的 key 必须与 after_reflect() 的返回值匹配（节点名）：
    #   "__end__" → END
    #   "synth"   → synth 节点
    #   "iter"    → iter 节点
    workflow.add_conditional_edges(
        "reflect",
        after_reflect,
        {
            "__end__": END,
            "synth": "synth",
            "iter": "iter",
        },
    )

    return workflow.compile()
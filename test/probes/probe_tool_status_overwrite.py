"""探针：同一轮里两次调用同一个工具（一次成功一次超时），tool_status 会怎样？

修复前（key = 工具名）：{'rag_search': 'timeout'} —— 成功那条被覆盖
修复后（key = 调用 id）：两条各存各的

不连 Milvus、不调 LLM：工具是假的。
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.errors import AgentTimeoutError
from agent.nodes.status_tool_wrapper import status_wrapper
from agent.state import AgentState


@tool
def rag_search(query: str) -> str:
    """假工具：query 里带 'fail' 就超时，否则返回内容。"""
    if "fail" in query:
        raise AgentTimeoutError("模拟超时")
    return f"关于 {query} 的检索结果"


def fake_iter(state: dict) -> dict:
    """假决策节点：一次发两个 rag_search tool_calls（一个会超时）。"""
    return {
        "messages": [AIMessage(content="", tool_calls=[
            {"name": "rag_search", "args": {"query": "正常问题"}, "id": "call_ok"},
            {"name": "rag_search", "args": {"query": "fail 这个问题"}, "id": "call_timeout"},
        ])]
    }


def main() -> None:
    workflow = StateGraph(AgentState)
    workflow.add_node("iter", fake_iter)
    workflow.add_node("tools", ToolNode([rag_search], wrap_tool_call=status_wrapper))
    workflow.set_entry_point("iter")
    workflow.add_edge("iter", "tools")
    workflow.add_edge("tools", END)
    graph = workflow.compile()

    result = graph.invoke({"messages": []})

    print("=== tool_status 最终值 ===")
    for call_id, info in result.get("tool_status", {}).items():
        print(f"  {call_id:16s} → {info}")

    print()
    print("=== 实际产生的 ToolMessage ===")
    for m in result["messages"]:
        if hasattr(m, "tool_call_id"):
            print(f"  id={m.tool_call_id:14s} content={m.content!r}")

    ts = result.get("tool_status", {})
    print()
    print(f"状态字典里有 {len(ts)} 个键: {list(ts.keys())}")
    if len(ts) == 2:
        print("→ ✅ 两次调用各留一条状态，没有互相覆盖")
    else:
        print("→ ❌ 两次调用只留下 1 条状态，超时的那个把成功的覆盖了")


if __name__ == "__main__":
    main()

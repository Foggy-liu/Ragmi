"""探针：iter 第 3 次决策发出的 tool_calls 到底会不会悬空？

「悬空」= AIMessage 里有 tool_calls，但没有对应的 ToolMessage。
MiniMax 收到这种消息序列会报 400（见 probe_minimax_dangling_400.py）。

修复前：悬空 2 / 总调用 7
修复后：悬空 0 / 总调用 5

需要 Milvus + MiniMax（跑真实图）。
"""
import os
import sys
import time

sys.path.insert(0, os.getcwd())

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.constants import TOTAL_TIMEOUT
from agent.graph import build_graph

QUESTION = "根据知识库帮我整理一下我最近关于 agent 学习笔记的几个要点"


def main() -> None:
    graph = build_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(QUESTION)], "deadline": time.time() + TOTAL_TIMEOUT},
        config={"recursion_limit": 42},
    )

    msgs = result["messages"]

    called_ids = []
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                called_ids.append((tc["id"], tc["name"]))
    answered = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage)}

    print("=== AIMessage 发出的 tool_calls ===")
    for cid, name in called_ids:
        mark = "OK " if cid in answered else "💥 悬空"
        print(f"  {mark}  id={cid}  tool={name}")

    dangling = [(c, n) for c, n in called_ids if c not in answered]
    print()
    print(f"悬空数量: {len(dangling)} / 总调用 {len(called_ids)}")
    print(f"tool_status 条目数: {len(result.get('tool_status', {}))}")
    print(f"iter_count = {result.get('iter_count')}  reflection_count = {result.get('reflection_count')}")

    print()
    print("=== 最终答案 ===")
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None) and m.content:
            print(" ", (m.content or "")[:200])
            break

    if dangling:
        print()
        print("❌ 存在悬空 tool_calls —— 一旦把 messages 传给 LLM（多轮记忆），MiniMax 会报 400")
    else:
        print()
        print("✅ 没有悬空 tool_calls")


if __name__ == "__main__":
    main()

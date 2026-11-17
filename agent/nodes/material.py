"""agent/nodes/material.py —— 本轮工具素材采集（方向 A）。

素材本来就在 ``state["messages"]`` 里：LangGraph 的 ``add_messages`` reducer
会自动把工具返回的 ToolMessage 追加进消息列表。所以节点只要自己**读出来**
拼进 prompt 即可，不需要新增 state 字段。

轮次边界：``messages`` 里"最后一条 HumanMessage 之后"的内容 = 本轮。
上一次提问之前的内容属于历史轮次，不会被误读进来。

三个节点（iter / synth / reflect）统一调这个函数，保证取到的素材范围一致。
"""
from langchain_core.messages import HumanMessage, ToolMessage


def collect_round_material(messages: list) -> str:
    """取出本轮（最后一条 HumanMessage 之后）的全部 ToolMessage 内容。

    Args:
        messages: state["messages"]

    Returns:
        拼接后的素材文本；本轮没有工具素材时返回空字符串
    """
    if not messages:
        return ""

    # 本轮起点：最后一条 HumanMessage 的下一个位置
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            start = i + 1
            break

    chunks = []
    for msg in messages[start:]:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content
        if not isinstance(content, str):
            content = str(content)
        if not content:
            continue
        name = getattr(msg, "name", "") or "工具"
        chunks.append(f"【{name}】\n{content}")

    return "\n\n".join(chunks)

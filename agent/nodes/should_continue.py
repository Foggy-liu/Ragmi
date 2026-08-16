"""agent/nodes/should_continue.py —— 条件边路由函数 (v2.2)。

v2.2 包含 2 个条件边：
- should_continue: iter → {tools, synth}
- after_reflect: reflect → {END, synth, iter}
"""
from agent.constants import MAX_ITER


def should_continue(state: dict) -> str:
    """iter 节点之后的条件路由。

    输入：state dict (含 messages, iter_count)
    输出："tools" / "synth"
    """
    # 兜底 1：迭代超限强制走 synth（让 reflect 接管，避免再调工具）
    if state.get("iter_count", 0) >= MAX_ITER:
        return "synth"

    last_message = state["messages"][-1]

    # 有工具调用 → tools
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # 默认（含 LLM 乱码 / READY 信号） → synth
    return "synth"


def after_reflect(state: dict) -> str:
    """reflect 节点之后的条件路由。

    输入：state dict (含 next_action)
    输出："__end__" / "synth" / "iter"
    """
    action = state.get("next_action", "end")
    if action == "end":
        return "__end__"
    if action == "rewrite":
        return "synth"
    if action == "re_iterate":
        return "iter"
    # 兜底：未知 action 走 END
    return "__end__"
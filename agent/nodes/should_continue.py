"""agent/nodes/should_continue.py —— 条件边路由函数 (v2.1)。

agent_node 之后路由：
- iterations >= MAX_ITERS → END（兜底）
- 有 tool_calls → tools
- 否则 → reflect（v2.1 新增分支）

reflect_node 之后路由（after_reflect）：
- last_reflection_pass → END
- 否则 → agent（带 critique 重答）
"""

from agent.state import MAX_ITERS


def should_continue(state: dict) -> str:
    """agent_node 之后的条件路由。

    输入：state dict (含 messages, iterations)
    输出："tools" / "reflect" / "__end__"
    """
    # 兜底 1：迭代超限
    if state.get("iterations", 0) >= MAX_ITERS:
        return "__end__"

    last_message = state["messages"][-1]

    # 有工具调用
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # 无工具调用 → 走反思（v2.1 新增）
    return "reflect"


def after_reflect(state: dict) -> str:
    """reflect_node 之后的条件路由。

    输入：state dict (含 last_reflection_pass)
    输出："agent" / "__end__"
    """
    if state.get("last_reflection_pass", False):
        return "__end__"
    return "agent"

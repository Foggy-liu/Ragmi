"""agent/runtime.py —— 对外统一调用入口。

App 层（main.py / main_web.py / API 层）只调这一个函数。
"""

from agent.graph import build_graph


_graph = None


def _get_graph():
    """懒加载 graph 单例。"""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def ask(question: str, session_id: str | None = None) -> str:
    """统一对话入口。

    输入：
    - question: 用户问题
    - session_id: 会话 ID（暂未启用多轮持久化，保留给未来 checkpoint）

    输出：agent 最终回答文本
    """
    graph = _get_graph()
    config = {"configurable": {"thread_id": session_id}} if session_id else None

    result = graph.invoke(
        {"messages": [("user", question)]},
        config=config,
    )

    return result["messages"][-1].content

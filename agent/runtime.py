"""agent/runtime.py —— 对外统一调用入口 (v2.2)。

v2.2 变化：
- debug 模式返回 6 字段：answer / iter_count / synth_count / reflection_count / tool_called / last_action
- last_action 来自 state.next_action（reflect 节点的输出）
- 删除 score 字段（v2.1 由 last_reflection_pass 推导，v2.2 用 last_action 替代）
"""
from langchain_core.messages import AIMessage

from agent.graph import build_graph
from utils.logging import get_logger

logger = get_logger(__name__)


_graph = None


def _get_graph():
    """懒加载 graph 单例。"""
    global _graph
    if _graph is None:
        _graph = _graph()
    return _graph


def _extract_answer(messages: list) -> str:
    """从 messages 中提取最后一条 AIMessage 的内容作为答案。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content or ""
    return ""


def _error_response(debug: bool):
    msg = "抱歉，agent 调用异常，请稍后重试。"
    if not debug:
        return msg
    return {
        "answer": msg,
        "iter_count": 0,
        "synth_count": 0,
        "reflection_count": 0,
        "tool_called": False,
        "last_action": "error",
    }


def ask(
    question: str,
    session_id: str | None = None,
    debug: bool = False,
) -> str | dict:
    """统一对话入口。

    输入：
    - question: 用户问题
    - session_id: 会话 ID（暂未启用多轮持久化）
    - debug: 是否返回 metadata dict（默认 False 返回 str）

    输出：
    - debug=False: 纯文本答案
    - debug=True: {"answer", "iter_count", "synth_count", "reflection_count", "tool_called", "last_action"}
    """
    graph = _get_graph()
    config = {"configurable": {"thread_id": session_id}} if session_id else None

    logger.info(f"ask() entry: query={question[:50]}... session={session_id}")

    try:
        from langchain_core.messages import HumanMessage
        result = graph.invoke(
            {"messages": [HumanMessage(question)]},
            config=config,
        )
    except Exception as e:
        logger.exception(f"ask() failed: {type(e).__name__}: {e}")
        return _error_response(debug)

    answer = _extract_answer(result["messages"])

    if not debug:
        return answer

    # debug 模式：返回 6 字段 metadata
    return {
        "answer": answer,
        "iter_count": result.get("iter_count", 0),
        "synth_count": result.get("synth_count", 0),
        "reflection_count": result.get("reflection_count", 0),
        "tool_called": bool(result.get("tool_status", {})),
        "last_action": result.get("next_action", "end"),
    }
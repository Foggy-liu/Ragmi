"""agent/runtime.py —— 对外统一调用入口 (v2.1)。

App 层（main.py / main_web.py / API 层）只调这一个函数。

v2.1 增强：
- 异常统一兜底（LLM 调用失败 / 超时不会 500）
- debug 模式返回 metadata（iterations / reflection_count / score / tool_called）
"""

from agent.graph import build_graph
from utils.logging import get_logger

logger = get_logger(__name__)


_graph = None


def _get_graph():
    """懒加载 graph 单例。"""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _compute_score(result: dict):
    """从 reflection_count + last_reflection_pass 推导 score。

    - None: 没触发反思（直接通过的简单 chat / RAG）
    - True: 反思触发且通过
    - False: 反思判不足但 MAX_REFL 兜底放行（需人工 review）
    """
    refl_count = result.get("reflection_count", 0)
    if refl_count == 0:
        return None
    return bool(result.get("last_reflection_pass", False))


def _error_response(debug: bool):
    msg = "抱歉，agent 调用异常，请稍后重试。"
    if not debug:
        return msg
    return {
        "answer": msg,
        "iterations": 0,
        "reflection_count": 0,
        "score": None,
        "tool_called": False,
        "error": True,
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
    - debug=True: {"answer", "iterations", "reflection_count", "score", "tool_called"}
    """
    graph = _get_graph()
    config = {"configurable": {"thread_id": session_id}} if session_id else None

    logger.info(f"ask() entry: query={question[:50]}... session={session_id}")

    try:
        result = graph.invoke(
            {"messages": [("user", question)]},
            config=config,
        )
    except Exception as e:
        logger.exception(f"ask() failed: {type(e).__name__}: {e}")
        return _error_response(debug)

    answer = result["messages"][-1].content

    if not debug:
        return answer

    # debug 模式: 返回 metadata
    tool_called = any(
        msg.__class__.__name__ == "ToolMessage"
        for msg in result["messages"]
    )
    return {
        "answer": answer,
        "iterations": result.get("iterations", 0),
        "reflection_count": result.get("reflection_count", 0),
        "score": _compute_score(result),
        "tool_called": tool_called,
    }

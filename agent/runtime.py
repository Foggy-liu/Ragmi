"""agent/runtime.py —— 对外统一调用入口 (v2.2)。

v2.2 变化：
- debug 模式返回 5 字段：answer / iter_count / reflection_count / tool_called / last_action
- last_action 来自 state.next_action（reflect 节点的输出）
- 删除 score 字段（v2.1 由 last_reflection_pass 推导，v2.2 用 last_action 替代）
"""
import time

from langchain_core.messages import AIMessage

from agent.constants import INTERNAL_SIGNALS, MAX_ITER, MAX_REFL, TOTAL_TIMEOUT
from agent.graph import build_graph
from utils.logging import get_logger

logger = get_logger(__name__)

# 图的循环预算：给 LangGraph 的 recursion_limit 兜底。
# 最坏情况 = 每轮 re_iterate 步数 × reflect 轮数
#   每轮：iter/tools 交替最多 2*MAX_ITER 步 + synth + reflect = 2*MAX_ITER + 2
#   轮数：reflect 最多被调用 MAX_REFL+1 次（最后一次进 reflect 时 count 已达上限，强制 end）
# 默认 25 不够（MAX_ITER=3/MAX_REFL=3 时最坏 8×4 = 32 步）→ 撞 GraphRecursionError，
# 表现为 ask() 兜底成"agent 调用异常"，而不是给出答案。
_STEPS_PER_ROUND = 2 * MAX_ITER + 2
RECURSION_LIMIT = _STEPS_PER_ROUND * (MAX_REFL + 1) + 10


_graph = None


def _get_graph():
    """懒加载 graph 单例。

    注意：右边必须是 build_graph()（调用造图函数），不能写成 _graph()——
    那是"把变量 _graph 当函数调用"，而它的值是 None → TypeError。
    """
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _extract_answer(messages: list) -> str:
    """从 messages 中提取答案（跳过 iter 的内部信号）。

    ⚠️ "倒着找最后一条 AIMessage"是不够的 —— iter 节点会往 messages 里塞内部信号
    （"READY" / "已达迭代上限，结束" / "已达总时限，停止思考"），那些是给下游节点看的
    流程标记，不是答案。图超时时直接停在 iter 的占位消息上，照搬就等于把
    「已达总时限，停止思考」当成答案交给用户（项目现状.md §2.8 / F9a_x）。

    返回空串表示"messages 里没有真答案"（调用方决定兜底话术）。
    """
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        content = (msg.content or "").strip()
        if content and content not in INTERNAL_SIGNALS:
            return content
    return ""


def _error_response(debug: bool):
    msg = "抱歉，agent 调用异常，请稍后重试。"
    if not debug:
        return msg
    return {
        "answer": msg,
        "iter_count": 0,
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
    - debug=True: {"answer", "iter_count", "reflection_count", "tool_called", "last_action"}
    """
    config = {"recursion_limit": RECURSION_LIMIT}
    if session_id:
        config["configurable"] = {"thread_id": session_id}

    logger.info(f"ask() entry: query={question[:50]}... session={session_id}")

    try:
        from langchain_core.messages import HumanMessage

        graph = _get_graph()
        result = graph.invoke(
            {
                "messages": [HumanMessage(question)],
                # 图级总时限：绝对时间戳，各节点用 is_expired(state) 协作式检查。
                # 放 state 而不是全局变量 —— state 每次 invoke 天然隔离，不会有并发串味。
                "deadline": time.time() + TOTAL_TIMEOUT,
            },
            config=config,
        )
    except Exception as e:
        logger.exception(f"ask() failed: {type(e).__name__}: {e}")
        return _error_response(debug)

    answer = _extract_answer(result["messages"])
    if not answer:
        # 图停在内部信号上（超时收摊）→ 给一句人话，别交白
        answer = "回答超时：思考时间超过总时限"

    if not debug:
        return answer

    # debug 模式：返回 5 字段 metadata
    return {
        "answer": answer,
        "iter_count": result.get("iter_count", 0),
        "reflection_count": result.get("reflection_count", 0),
        "tool_called": bool(result.get("tool_status", {})),
        "last_action": result.get("next_action", "end"),
    }
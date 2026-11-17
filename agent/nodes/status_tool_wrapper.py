"""agent/nodes/status_tool_wrapper.py —— 工具调用状态捕获（v2.2 官方钩子版 + 状态结构化）。

用 LangGraph 官方钩子 ``ToolNode(wrap_tool_call=...)`` 拦截每次工具调用，
把执行状态写进 ``state["tool_status"]`` 字典。

4 种 status 值：
- success: 工具返回非空内容
- empty:   工具返回空内容
- timeout: 工具抛 AgentTimeoutError（超时）
- error:   工具抛 AgentToolError 或其他异常

## 状态字典的结构

key = **调用 id**（不是工具名）
    调用 id 由模型生成、每次调用唯一。同一轮里 MiniMax 常常并发调同一个工具
    2~3 次（例如同时发 2 个 rag_search），按工具名做 key 会让后一次调用
    覆盖前一次的状态（实测：成功的那条被 timeout 冲掉）。
    用调用 id 做 key 天然不冲突。

value = 结构化小对象 ``{tool, status, code, retryable}``
    - tool      : 工具名（渲染时按它分组）
    - status    : 上面 4 种之一
    - code      : 机器可读失败码（OK / EMPTY_RESULT / TOOL_TIMEOUT / TOOL_ERROR）
    - retryable : 该失败重试有没有意义

## 为什么 ToolMessage 用结构化载荷

失败时 ToolMessage 的内容是 JSON 而不是中文散文：
    {"code": "TOOL_TIMEOUT", "status": "timeout", "retryable": true, "message": "调用超时：..."}
理由：ToolMessage 是给 LLM 看的，结构化载荷比散文更明确；也能被测试直接断言，
不依赖 prompt 措辞。成功时内容保持原样（原始检索片段），不做包装。

## 为什么不用"继承 ToolNode 再重写 __call__"
ToolNode.__init__ 里 ``super().__init__(self._func, self._afunc, ...)`` 把
"被调用的方法"钉死成 ``_func``；LangGraph 走的是 ``node.invoke(...)`` →
``self.func`` → 父类原版 _func，子类重写的 ``__call__`` 永远不会被执行。
``wrap_tool_call`` 是框架 1.0.5 提供的官方拦截点，不碰内部实现。

兜底：timeout/error 时仍必须写 ToolMessage，否则 graph 卡在"有 tool_calls 但没应答"。
"""
import json

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent.errors import AgentError, AgentTimeoutError


# 状态词汇表：status → (code, retryable, 默认中文说明)
#
# retryable 语义 = "这个失败重试有没有意义"。
# 当前只有 timeout 为 True；更细的分类（限流/服务不可用 → 可重试，
# 参数错/代码 bug → 不可重试）暂时做不了 —— 工具层目前只拿到
# `AgentToolError` 这一个"其他错误"的桶，看不出底层到底是限流还是参数错。
#
# ✅ 2026-11-17（P2-7）：`core/rags/rags.py` 的 retrieve() 不再把异常吞成 []，
# 改为抛 RetrievalError → 工具层能区分「超时」（→ AgentTimeoutError，可重试）
# 和「其他错误」（→ AgentToolError）。再细分需要 RetrievalError 带更细的错误码。
STATUS_META: dict[str, tuple[str, bool, str]] = {
    "success": ("OK", False, ""),
    "empty": ("EMPTY_RESULT", False, "工具返回空内容"),
    "timeout": ("TOOL_TIMEOUT", True, "调用超时"),
    "error": ("TOOL_ERROR", False, "工具执行失败"),
}


def _status_entry(tool_name: str, status: str) -> dict:
    """构造 tool_status 的 value：{tool, status, code, retryable}。"""
    code, retryable, _ = STATUS_META[status]
    return {
        "tool": tool_name,
        "status": status,
        "code": code,
        "retryable": retryable,
    }


def status_wrapper(request, execute) -> Command:
    """每次工具调用都经过这里一次。

    Args:
        request: ToolCallRequest —— request.tool_call = {"name", "args", "id"}
        execute: 真正执行这次调用的可调用对象（可多次调用，用于重试）

    Returns:
        Command：update 里带 messages（ToolMessage）和 tool_status（状态字典）
    """
    tool_call = request.tool_call
    tool_name = tool_call["name"]
    tool_call_id = tool_call["id"]

    try:
        result = execute(request)
    except AgentTimeoutError as e:
        return _failure(tool_name, tool_call_id, "timeout", f"调用超时：{e}")
    except AgentError as e:
        return _failure(tool_name, tool_call_id, "error", f"工具异常：{e}")
    except Exception as e:
        # 兜底：某个工具忘了归一化，原始异常直接漏出来了
        return _failure(tool_name, tool_call_id, "error", f"工具异常：{type(e).__name__}: {e}")

    content = getattr(result, "content", "")
    status = "success" if content else "empty"
    return Command(update={
        "messages": [result],
        "tool_status": {tool_call_id: _status_entry(tool_name, status)},
    })


def _failure(tool_name: str, tool_call_id: str, status: str, message: str) -> Command:
    """工具失败时的兜底返回：既要写 ToolMessage（结构化载荷），也要写状态。"""
    code, retryable, _ = STATUS_META[status]
    payload = json.dumps(
        {
            "code": code,
            "status": status,
            "retryable": retryable,
            "message": message,
        },
        ensure_ascii=False,
    )
    return Command(update={
        "messages": [ToolMessage(
            content=payload,
            tool_call_id=tool_call_id,
            name=tool_name,
        )],
        "tool_status": {tool_call_id: _status_entry(tool_name, status)},
    })


def format_tool_status(tool_status: dict) -> str:
    """把 tool_status 渲染成给 LLM 看的一行一条（按工具名分组）。

    同一个工具被并发调用多次时，组内会列出多个状态，不会互相覆盖
    （改动前按工具名做 key，只会留下最后一次）。

    渲染文本刻意贴近改动前的格式（"- 工具名: status"），避免 prompt 文本
    漂移影响 LLM 既有决策习惯。
    """
    if not tool_status:
        return "（无工具调用）"

    grouped: dict[str, list[str]] = {}
    for info in tool_status.values():
        grouped.setdefault(info.get("tool", "工具"), []).append(info.get("status", "unknown"))

    lines = [f"- {name}: " + "；".join(statuses) for name, statuses in grouped.items()]
    return "\n".join(lines)

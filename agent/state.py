"""RAGMI Agent State —— LangGraph 状态契约 (v2.2 + 超时改造)。

9 字段 schema：
- messages: 消息历史（add_messages reducer）
- iter_count: iter 节点计数器（_inc_iter reducer）
- reflection_count: reflect 节点计数器（_inc_refl reducer）
- tool_status: 工具调用状态字典，key=调用 id（_merge_tool_status reducer）
- last_critique: reflect 节点输出的反馈（synth 重写模式读）
- next_action: reflect 节点输出的下一步动作（end/rewrite/re_iterate）
- deadline: 图级总时限（绝对时间戳，float）
- expired: 是否已超时（True 时条件边直接 END）
- last_answer: synth 最近一次写出的答案（超时兜底时交出去）

替代 v2.1 的 iterations + last_reflection_pass。
"""
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ===== Reducer =====

def _reset_or_inc(old: int, new: int) -> int:
    """带重置语义的累加 reducer（用于 iter_count）。

    LangGraph reducer 默认是纯累加：(old or 0) + (new or 0)。
    但 reflect_node 需要"重置"语义（rewrite/re_iterate 时把 iter 归 0），
    用累加 reducer 做不到（旧 + 0 = 旧）。

    约定：
    - 节点返回 0 → 显式重置（reflect_node 用）
    - 节点返回 > 0 → 累加（iter_node 用）
    """
    if new == 0:
        return 0
    return (old or 0) + (new or 0)


# 向后兼容别名（测试 plan 中已引用 _inc_iter）
_inc_iter = _reset_or_inc


def _inc_refl(old: int, new: int) -> int:
    """reflection_count 字段 reducer：永远累加（绝对上限，不重置）。"""
    return (old or 0) + (new or 0)


def _merge_tool_status(old: dict, new: dict) -> dict:
    """tool_status 字段 reducer：按调用 id 合并。

    key 是调用 id（不是工具名）—— 同一轮里同一个工具可能被并发调用多次
    （MiniMax 一次决策常发 2~3 个 tool_calls），按工具名做 key 会互相覆盖。
    """
    return {**(old or {}), **(new or {})}


# ===== State Schema =====

class AgentState(TypedDict, total=False):
    """v2.2 Agent 运行时状态。

    字段说明
    --------
    messages : list[BaseMessage]
        消息历史（add_messages reducer）。
    iter_count : int
        iter 节点调用次数。reflect 触发 rewrite/re_iterate 时重置为 0。
    reflection_count : int
        reflect 节点调用次数。永不重置（绝对上限）。
    tool_status : dict[str, dict]
        工具调用状态字典。key = 调用 id（每次调用唯一），
        value = {tool, status, code, retryable}：
        tool=工具名，status=success/empty/timeout/error，
        code=机器可读失败码，retryable=该失败重试有没有意义。
    last_critique : str
        reflect 节点最新输出的 critique；synth 重写模式时读取。
    next_action : str
        reflect 节点输出的下一步动作（end / rewrite / re_iterate）。
        必须声明在 schema 里，否则不会落进 state —— 条件边照样能读到
        （它拿的是节点的原始返回值），但 state 里没有 → runtime 取不到。
    deadline : float
        图级总时限（time.time() 绝对时间戳）。节点用 is_expired() 检查。
    expired : bool
        是否已超时。True 时条件边直接路由到 END，不再继续迭代。
    last_answer : str
        synth 节点最近一次写出的答案。
        单独存一份是因为 messages 里混着 iter 的占位消息（"READY" 等），
        光看"最后一条 AIMessage"会把占位消息当成答案交出去。
    """
    messages: Annotated[list[BaseMessage], add_messages]
    iter_count: Annotated[int, _inc_iter]
    reflection_count: Annotated[int, _inc_refl]
    tool_status: Annotated[dict[str, dict], _merge_tool_status]
    last_critique: str
    next_action: str
    deadline: float
    expired: bool
    last_answer: str


def initial_state(question: str) -> AgentState:
    """构造 Agent 初始 state。"""
    return {
        "messages": [],
        "iter_count": 0,
        "reflection_count": 0,
        "tool_status": {},
        "last_critique": "",
        "next_action": "",
        "deadline": 0.0,
        "expired": False,
        "last_answer": "",
    }

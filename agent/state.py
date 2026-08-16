"""RAGMI Agent State —— LangGraph 状态契约 (v2.2)。

6 字段 schema：
- messages: 消息历史（add_messages reducer）
- iter_count: iter 节点计数器（_inc_iter reducer）
- synth_count: synth 节点计数器（_inc_synth reducer）
- reflection_count: reflect 节点计数器（_inc_refl reducer）
- tool_status: 多工具状态字典（_merge_tool_status reducer）
- last_critique: reflect 节点输出的反馈（synth 重写模式读）

替代 v2.1 的 iterations + last_reflection_pass。
"""
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ===== Reducer =====

def _inc_iter(old: int, new: int) -> int:
    """iter_count 字段 reducer：节点返回增量，框架累加。"""
    return (old or 0) + (new or 0)


def _inc_synth(old: int, new: int) -> int:
    """synth_count 字段 reducer。"""
    return (old or 0) + (new or 0)


def _inc_refl(old: int, new: int) -> int:
    """reflection_count 字段 reducer。"""
    return (old or 0) + (new or 0)


def _merge_tool_status(old: dict, new: dict) -> dict:
    """tool_status 字段 reducer：合并而非覆盖（多工具串行调用时）。"""
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
    synth_count : int
        synth 节点调用次数。reflect 触发时重置为 0。
    reflection_count : int
        reflect 节点调用次数。永不重置（绝对上限）。
    tool_status : dict[str, str]
        多工具状态字典（rag_search: success / calculator: timeout ...）。
    last_critique : str
        reflect 节点最新输出的 critique；synth 重写模式时读取。
    """
    messages: Annotated[list[BaseMessage], add_messages]
    iter_count: Annotated[int, _inc_iter]
    synth_count: Annotated[int, _inc_synth]
    reflection_count: Annotated[int, _inc_refl]
    tool_status: Annotated[dict[str, str], _merge_tool_status]
    last_critique: str


def initial_state(question: str) -> AgentState:
    """构造 Agent 初始 state。"""
    return {
        "messages": [],
        "iter_count": 0,
        "synth_count": 0,
        "reflection_count": 0,
        "tool_status": {},
        "last_critique": "",
    }

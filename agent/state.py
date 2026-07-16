"""RAGMI Agent State —— LangGraph 状态契约 (v2.1)。

所有 node / edge / tool 都对 AgentState 做读和写。
本文件定义了图运行期间的"数据形状"，是其他组件依赖的契约。
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ===== v2.1 新增常量 =====
# 上限：agent_node 最多被调 5 次（含决策/综合/重答）
MAX_ITERS = 5
# 上限：reflect_node 最多被调 1 次（第 2 次边际收益<10%）
MAX_REFL = 1


def _increment(old: int, new: int) -> int:
    """iterations 字段的 reducer：把节点返回的增量累加到当前值。

    用法：agent_node 每次 return {"iterations": 1}，框架自动 +1。
    若直接覆盖（lambda old, new: new），需要节点自己读 state.get() + 1，代码更冗长。
    """
    return (old or 0) + (new or 0)


class AgentState(TypedDict, total=False):
    """Agent 运行时状态。

    total=False 表示：所有字段都可选，新建会话可直接传入空 dict 起步。

    字段说明
    --------
    messages : list[BaseMessage]
        消息历史（用户 / AI / 工具三类轮流出现）。
        add_messages 是 LangGraph 的 reducer：每个节点 return {"messages": [...]} 时，
        引擎调用 add_messages 决定如何合并到现有 messages。

    iterations : int
        agent 节点执行次数计数器。超 MAX_ITERS 强制 END（should_continue 里检查）。

    reflection_count : int  ← v2.1 新增
        reflect_node 执行次数计数器。超 MAX_REFL 强制 pass（reflect_node 里检查）。

    last_reflection_pass : bool  ← v2.1 新增
        最近一次 reflect_node 评判结果。条件边 after_reflect 读这个决定路由。
        - True → END（通过）
        - False → agent（带 critique 重答）
    """

    messages: Annotated[list[BaseMessage], add_messages]
    iterations: Annotated[int, _increment]
    reflection_count: Annotated[int, _increment]
    last_reflection_pass: bool

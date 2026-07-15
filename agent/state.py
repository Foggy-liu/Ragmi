"""RAGMI Agent State —— LangGraph 状态契约。

所有 node / edge / tool 都对 AgentState 做读和写。
本文件定义了图运行期间的"数据形状"，是其他组件依赖的契约。
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


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
        引擎调用 add_messages 决定如何合并到现有 messages（自动追加 + 同 id 合并 +
        ToolMessage 关联校验）。

    iterations : int
        agent 节点执行次数计数器。每次 agent_node 跑完自动 +1。
        用途：
        1. 防止死循环（rejection 条件可在 should_continue 里检查 state.iterations）
        2. 观测/调试用：知道这个对话跑了多少轮
        3. 后续可拓展：超过 N 轮时强制结束 / 切换策略
    """

    messages: Annotated[list[BaseMessage], add_messages]
    iterations: Annotated[int, _increment]

"""RAGMI Agent State —— LangGraph 状态契约。

所有 node / edge / tool 都对 AgentState 做读和写。
本文件定义了图运行期间的"数据形状"，是其他组件依赖的契约。
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


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
    """

    messages: Annotated[list[BaseMessage], add_messages]

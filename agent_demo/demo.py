"""
Agent 最小 Demo - LangGraph 入门
==================================

[目标]  ~200 行代码，让你"看见"一个 Agent 是怎么工作的

[运行]  python agent_demo/demo.py

[演示]  你将看到 3 个示例：
    1. 单工具调用：5 + 3 = ?
    2. 多步循环：先查天气，再算加法
    3. 不调工具：普通聊天

[核心]  按代码顺序：
    1. Tools       - 让 LLM 能"做实事"的函数（@tool 装饰器）
    2. LLM         - 决策者（这里用 MockLLM，不用 API key）
    3. AgentState  - Agent 的"工作记忆"（TypedDict）
    4. Nodes       - 每一步动作（reasoning / tool_execution）
    5. StateGraph  - 把节点连成循环图
"""

from typing import TypedDict, Annotated
import operator
import re

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool


# ============================================================
# 1. 定义工具（Tools）
# ============================================================
# LangGraph 通过 @tool 装饰器识别工具
# LLM 看到的工具描述 = 函数名 + docstring + 类型注解
# 这就是 "function calling" 的基础

@tool
def add(a: int, b: int) -> int:
    """计算两个整数相加。输入 a 和 b，返回它们的和。"""
    return a + b


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。输入城市名，返回天气描述。"""
    # Mock 数据（真实场景是调天气 API）
    mock_weather = {
        "北京": "晴天，气温 25 度，适宜出行",
        "上海": "多云，气温 28 度，记得带伞",
        "广州": "小雨，气温 30 度，注意防潮",
    }
    return mock_weather.get(city, f"{city}：暂无天气数据")


tools = [add, get_weather]


# ============================================================
# 2. Mock LLM（决策者）
# ============================================================
# 真实场景：LLM 看到工具描述 + 用户问题，输出结构化 tool_call
# 这里用 Mock 是为了让你不需要 API key 就能跑
# 真实接 ChatOpenAI 等只要替换这个类

class MockLLM:
    """模拟 LLM：根据用户输入，决定调哪个工具 / 直接回答"""

    def invoke(self, messages):
        last_msg = messages[-1]

        # 情况 1：用户提问 -> 决定调哪个工具
        if isinstance(last_msg, HumanMessage):
            text = last_msg.content

            # 规则 1：检测到城市名 -> 调 get_weather
            for city in ["北京", "上海", "广州"]:
                if city in text:
                    print(f"  [LLM 决策] -> 调用 get_weather(city='{city}')")
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "get_weather",
                            "args": {"city": city},
                            "id": f"call_{len(messages)}",
                        }],
                    )

            # 规则 2：检测 "a + b" 模式 -> 调 add
            nums = re.findall(r"(\d+)\s*\+\s*(\d+)", text)
            if nums:
                a, b = int(nums[0][0]), int(nums[0][1])
                print(f"  [LLM 决策] -> 调用 add(a={a}, b={b})")
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "add",
                        "args": {"a": a, "b": b},
                        "id": f"call_{len(messages)}",
                    }],
                )

            # 规则 3：都不匹配 -> 直接回答（不调工具）
            print(f"  [LLM 决策] -> 不需要工具，直接回答")
            return AIMessage(content=f"你说的是：{text}。我直接回答你~")

        # 情况 2：工具返回结果 -> 综合最终答案
        elif isinstance(last_msg, ToolMessage):
            print(f"  [LLM 决策] -> 工具结果已收到，综合最终答案")
            return AIMessage(content=f"查询结果：{last_msg.content}")

        return AIMessage(content="无法处理")


llm = MockLLM()


# ============================================================
# 3. Agent 状态（State）- 工作记忆
# ============================================================

class AgentState(TypedDict):
    """Agent 状态：消息列表，每步追加"""
    messages: Annotated[list, operator.add]


# ============================================================
# 4. 节点（Nodes）- 每一步动作
# ============================================================

def reasoning_node(state: AgentState) -> dict:
    """思考节点：让 LLM 决定下一步"""
    print("\n[思考节点] 调用 LLM...")
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


def tool_execution_node(state: AgentState) -> dict:
    """工具执行节点：执行 LLM 选的工具"""
    print("[工具执行节点] 执行工具...")
    last_msg = state["messages"][-1]

    results = []
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tool_call in last_msg.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            # 找到工具函数
            tool_fn = next(t for t in tools if t.name == tool_name)

            # 执行工具
            result = tool_fn.invoke(tool_args)
            print(f"  + {tool_name}({tool_args}) = {result}")

            # 包装成 ToolMessage 回喂给 LLM
            results.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_id,
            ))

    return {"messages": results}


def should_continue(state: AgentState) -> str:
    """判断继续循环还是结束"""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "continue"
    return "end"


# ============================================================
# 5. 构建 StateGraph（核心）
# ============================================================

def build_agent():
    graph = StateGraph(AgentState)

    # 加节点
    graph.add_node("reasoning", reasoning_node)
    graph.add_node("tool_execution", tool_execution_node)

    # 加固定边
    graph.add_edge(START, "reasoning")                    # 开始 -> 思考
    graph.add_edge("tool_execution", "reasoning")          # 工具结果回喂给 LLM

    # 加条件边：思考后判断继续还是结束
    graph.add_conditional_edges(
        "reasoning",
        should_continue,
        {
            "continue": "tool_execution",
            "end": END,
        },
    )

    return graph.compile()


# ============================================================
# 6. 跑起来
# ============================================================

if __name__ == "__main__":
    agent = build_agent()

    print("\n" + "=" * 60)
    print("[Agent Demo] LangGraph 入门")
    print("=" * 60)

    # 示例 1：单工具
    print("\n[示例 1] 单工具：5 + 3 等于多少？")
    print("-" * 60)
    result = agent.invoke({"messages": [HumanMessage(content="5 + 3 等于多少？")]})
    print(f"\n[最终答案] {result['messages'][-1].content}")

    # 示例 2：多步循环
    print("\n" + "=" * 60)
    print("\n[示例 2] 多步：先查北京天气，再算 10 + 20")
    print("-" * 60)
    result = agent.invoke({"messages": [HumanMessage(content="北京天气怎么样？然后算 10 + 20？")]})
    print(f"\n[最终答案] {result['messages'][-1].content}")

    # 示例 3：不调工具
    print("\n" + "=" * 60)
    print("\n[示例 3] 不需要工具：你好")
    print("-" * 60)
    result = agent.invoke({"messages": [HumanMessage(content="你好！")]})
    print(f"\n[最终答案] {result['messages'][-1].content}")

    print("\n" + "=" * 60)
    print("[完成] Demo 跑完！")
    print("=" * 60)
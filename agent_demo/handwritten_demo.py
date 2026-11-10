"""
Hand-written Agent —— 完全看清 LangGraph 在帮你做什么
========================================================

[目标]   不依赖任何 Agent 框架，从零写一个能跑的 ReAct Agent
[对比]   agent_demo/demo.py       —— LangGraph 版
        agent_demo/handwritten_demo.py —— 纯手搓版（这个文件）
[读完你会有 3 个收获]
    1. Agent 本质 = 4 个函数 + 1 个 while 循环
    2. LangGraph 的"魔法"是普通代码，不是魔法
    3. 自己写 vs 用框架的真实取舍

[核心循环 4 步]
    Reasoning  →  LLM 决定调什么工具
    Acting     →  执行工具，拿结果
    Observation →  把结果写回消息历史
    Continue?  →  不够 → 再来 / 够了 → 结束
"""

import re


# ============================================================
# 1. 工具定义（LangGraph 用 @tool 装饰器，这里直接写函数）
# ============================================================

def add(a: int, b: int) -> int:
    """计算两个整数相加"""
    return a + b


def get_weather(city: str) -> str:
    """查询指定城市的当前天气"""
    mock_weather = {
        "北京": "晴天，气温 25 度，适宜出行",
        "上海": "多云，气温 28 度，记得带伞",
        "广州": "小雨，气温 30 度，注意防潮",
    }
    return mock_weather.get(city, f"{city}：暂无天气数据")


# 工具注册表（LangGraph 用 bind_tools，这里用手写 dict）
TOOLS = {
    "add": add,
    "get_weather": get_weather,
}


# ============================================================
# 2. Mock LLM（决策者）
# ============================================================
# 真实场景：LLM 看到工具描述 + 用户问题，输出结构化 tool_call
# LangGraph 这里接 ChatOpenAI.bind_tools()，本文件用 Mock

class MockLLM:
    """模拟 LLM：根据用户输入，决定调哪个工具 / 直接回答"""

    def invoke(self, messages):
        last_msg = messages[-1]
        text = last_msg["content"] if isinstance(last_msg, dict) else last_msg.content

        # 规则 1：检测到城市名 -> 调 get_weather
        for city in ["北京", "上海", "广州"]:
            if city in text:
                return {
                    "content": "",
                    "tool_call": {
                        "name": "get_weather",
                        "args": {"city": city},
                        "id": f"call_{len(messages)}",
                    },
                }

        # 规则 2：检测 "a + b" 模式 -> 调 add
        nums = re.findall(r"(\d+)\s*\+\s*(\d+)", text)
        if nums:
            a, b = int(nums[0][0]), int(nums[0][1])
            return {
                "content": "",
                "tool_call": {
                    "name": "add",
                    "args": {"a": a, "b": b},
                    "id": f"call_{len(messages)}",
                },
            }

        # 规则 3：都不匹配 -> 直接回答（不调工具）
        return {
            "content": f"你说的是：{text}。我直接回答你~",
            "tool_call": None,
        }


llm = MockLLM()


# ============================================================
# 3. 状态管理（LangGraph 用 TypedDict + reducer，这里用普通 dict）
# ============================================================
# 我们手动管理所有"Agent 的记忆"

def make_initial_state(query):
    """初始化 Agent 状态"""
    return {
        "messages": [{"role": "user", "content": query}],   # 消息历史
        "current_step": 0,                                    # 当前步数
        "max_steps": 5,                                       # 最大步数（防死循环）
        "final_answer": None,                                 # 最终答案
        "trace": [],                                          # 每步 trace（调试用）
    }


# ============================================================
# 4. Agent 循环（LangGraph 用 StateGraph + add_edge，这里用 while）
# ============================================================
# 这是核心中的核心 —— LangGraph 把这段代码换成 add_edge/add_node

def run_agent(query):
    """主循环：ReAct Agent"""
    state = make_initial_state(query)

    print(f"\n[启动] 用户问题: {query}")

    # ========================================================
    # 主循环：每轮 = Reasoning + Acting + Observation
    # ========================================================
    while state["current_step"] < state["max_steps"]:
        state["current_step"] += 1
        print(f"\n--- 第 {state['current_step']} 步 ---")

        # ========== Step 1: Reasoning ==========
        # 调 LLM，看下一步该干嘛
        print("[Reasoning] 调 LLM 决策...")
        llm_response = llm.invoke(state["messages"])

        # ========== Step 2: Parse + Decide ==========
        # 解析 LLM 输出：要不要调工具？调哪个？
        tool_call = llm_response["tool_call"]

        if tool_call is None:
            # ===> 没工具调用，直接出最终答案
            print(f"[Reasoning] LLM 说: '{llm_response['content']}'")
            print("[Decision] 不调工具，直接回答")
            state["final_answer"] = llm_response["content"]
            state["trace"].append({
                "step": state["current_step"],
                "thought": llm_response,
                "action": None,
                "observation": None,
            })
            break

        # ===> LLM 决定调工具
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        print(f"[Decision] 调工具: {tool_name}({tool_args})")

        # ========== Step 3: Acting ==========
        # 执行工具
        observation = TOOLS[tool_name](**tool_args)
        print(f"[Acting] {tool_name} 返回: {observation}")

        # ========== Step 4: Observation（回喂给 LLM）==========
        # 把"LLM 决定"和"工具结果"都加入消息历史
        state["messages"].append({
            "role": "assistant",
            "content": llm_response["content"],
            "tool_call": tool_call,
        })
        state["messages"].append({
            "role": "tool",
            "name": tool_name,
            "content": str(observation),
        })

        # 记录 trace（用于调试 / 前端可视化）
        state["trace"].append({
            "step": state["current_step"],
            "thought": llm_response,
            "action": {"name": tool_name, "args": tool_args},
            "observation": observation,
        })

    # ========== 循环结束判断 ==========
    if state["final_answer"] is None:
        # 达到最大步数还没出答案，强制结束
        print(f"\n[超时] 达到最大步数 {state['max_steps']}")
        state["final_answer"] = f"达到最大步数 {state['max_steps']}，未能完成"

    return state


# ============================================================
# 5. 跑起来
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("[Hand-written Agent] 不依赖任何 Agent 框架")
    print("=" * 60)

    # 示例 1：单工具
    print("\n" + "=" * 60)
    print("[示例 1] 单工具：5 + 3 等于多少？")
    print("-" * 60)
    result = run_agent("5 + 3 等于多少？")
    print(f"\n[最终答案] {result['final_answer']}")
    print(f"[总步数] {result['current_step']}")

    # 示例 2：直接回答
    print("\n" + "=" * 60)
    print("[示例 2] 不需要工具：你好")
    print("-" * 60)
    result = run_agent("你好！")
    print(f"\n[最终答案] {result['final_answer']}")
    print(f"[总步数] {result['current_step']}")

    print("\n" + "=" * 60)
    print("[完成] Demo 跑完！")
    print("=" * 60)
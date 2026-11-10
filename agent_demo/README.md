# Agent 最小 Demo —— LangGraph 入门

> 🎯 目的：用最少的代码让你"看见"一个 Agent 是怎么工作的。

## 怎么运行

```bash
# 装依赖（项目根目录执行）
pip install langgraph langchain-core

# 跑 demo
python agent_demo/demo.py
```

不需要 API key——用了 MockLLM 模拟决策。

## 你会看到什么

3 个示例分别演示：

| 示例 | 触发场景 | Agent 行为 |
|---|---|---|
| 1 | "5 + 3 等于多少？" | 调 `add` 工具 → 拿到结果 → 回答 |
| 2 | "北京天气怎么样？然后算 10 + 20？" | 调 `get_weather` → 再调 `add` → 综合回答（**多步循环**）|
| 3 | "你好！" | 不调工具 → 直接回答 |

## 核心概念（30 秒讲完）

| 概念 | 是什么 | 在代码哪里 |
|---|---|---|
| **Tool** | 让 LLM 能调用的函数 | `@tool` 装饰器 |
| **LLM** | 决策者（这里用 Mock） | `MockLLM` 类 |
| **State** | Agent 的"工作记忆" | `AgentState` TypedDict |
| **Node** | 每一步动作 | `reasoning_node` / `tool_execution_node` |
| **Edge** | 节点之间的连接 | `graph.add_edge()` |
| **Conditional Edge** | 条件分支（继续 vs 结束） | `graph.add_conditional_edges()` |

## Agent 循环的可视化

```
   ┌────────────────────────────────────┐
   │                                    │
   ▼                                    │
[START] → [思考节点 reasoning] ──→ [工具执行 tool_execution]
              │                          │
              │ 没工具调用                │ 把结果回喂
              ▼                          │
            [END]                        │
                                          │
              ↑ ← ← ← ← ← ← ← ← ← ← ← ┘
```

- **思考节点**：调 LLM，决定下一步调哪个工具 / 直接回答 / 还是结束
- **工具执行节点**：执行 LLM 选的工具，把结果包装回消息历史
- **条件边**：根据 LLM 的输出判断是继续循环还是结束

## 手写 vs LangGraph 对比

RAGMI 项目里有一套**手写的 Agent**（`agent/controller.py`）：
- 用正则 `[[rag]]` 解析 LLM 输出 → 简陋
- 工具只接 `query` 一个参数 → 不通用
- 手写循环、超时、降级、评估 → 大量胶水

**LangGraph 的优势**：
- ✅ 用 LLM 原生 tool_calls（结构化参数）
- ✅ 框架管理循环、状态、条件分支（少写一半代码）
- ✅ 行业标准（岗位关键词：function calling、StateGraph）
- ✅ 内置 checkpoint / streaming / 断点续跑

**什么时候手写有价值**：
- 极简场景（只有 1-2 个工具，且不会扩展）
- 学习阶段（理解底层——比如你现在的状态）
- 框架无法满足的极端定制需求

## 与 RAGMI M1 的关系

这是 M1 Agent v1 的**最小雏形**。
下一步（M1.3）会把这个 demo 扩展成：
- 工具替换为真实的 `RagTool` / `ChatTool`（带 JSON Schema）
- 替换 MockLLM 为真实的 `ChatOpenAI.bind_tools()`
- 接入 FastAPI 路由

详见 `docs/mettings/agent_deepening_plan.md` §3。

## 想自己改着玩？

- 加新工具：写个 `@tool` 函数，加进 `tools` 列表
- 改 MockLLM 决策规则：编辑 `MockLLM.invoke` 的 if-else
- 加节点：在 `graph.add_node` 注册新节点，用 `add_edge` 串联
- 改循环条件：编辑 `should_continue`

跑跑看、改改看——这是学 LangGraph 最快的方式。
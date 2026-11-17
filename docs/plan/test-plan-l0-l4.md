# RAGMI 项目测试方案（test1）

> **生成日期**：2026-11-10
> **测试对象**：**整个项目**（RAG 不是一个独立模块，而是 Agent 的一个工具 `rag_search`；但 RAG 侧仍有独立的入库/检索链路需要覆盖）
> **代码基准**：`agent-v2.2-graph-refactor` 分支未提交状态
> **配套文档**：`docs/note/next/项目优化step1.md`（P0/P1/P2 分级）

---

## 0. 先说现状（诚实版）

```bash
$ pytest --collect-only -q
3 tests collected
```

| 层级 | 现状 |
|---|---|
| 单测（纯逻辑，不依赖 LLM） | **3 个**：`test_main_routes_covered.py` × 2 + `test_vector_split.py` × 1 |
| v2.2 节点/图单测 | **0 个**（v2.1 的 `test_reflect.py` / `test_reflection_count.py` 在重构时被删，新的一直没写） |
| 评估脚本 | `run_agent_eval.py` **mock 模式已坏**（ImportError），真实模式没跑过 |
| LangSmith 评估 | 脚本在，但字段名过期 → `KeyError` |

**结论**：目前项目**没有任何一个测试在验证 v2.2 的核心机制**。
本文档要回答的问题就是：**要补哪些、补在哪、怎么断言**。

### 0.1 现有测试文件清单

| 文件 | 类型 | 依赖 | 状态 |
|---|---|---|---|
| `test/test_main_routes_covered.py` | pytest，AST 静态扫描 | 无 | ✅ 可跑。防止 `api/*.py` 定义了 router 却没挂载（历史教训：`api_vector.py` 死代码导致 `/vector` 404） |
| `test/test_vector_split.py` | pytest，E2E | **Milvus + Ollama** | ⚠️ Milvus 不在跑就失败 |
| `test/run_agent_eval.py` | 独立脚本 | LLM key + Milvus | ❌ `--mock` ImportError；`iterations` 字段名过期 |
| `test/run_v1_baseline.py` | 独立脚本 | 活着的 server | 调试草稿，v1 已不存在 |
| `test/retry_failed_cases.py` | 独立脚本 | 活着的 server | 调试草稿 |
| `test/evil_proxy.py` / `test/repro_embed_clients.py` | 独立脚本 | 本地 Ollama | 调试草稿（排查代理 52266 端口用） |
| `test/langsmith_setup.py` / `langsmith_eval.py` / `langsmith_evaluators.py` | 独立脚本 | LangSmith key | ⚠️ 字段名过期 |
| `test/api_dashboard.html` | 手工浏览器面板 | 活着的 server | 手工 |

---

## 1. 测试分层（先建立概念）

> **一句话**：越往下越便宜、越快、越该多写；越往上越贵、越慢、越该少写。

```
L0  纯逻辑单测      ——  不碰 LLM / Milvus / 网络，毫秒级    ← 今天几乎为零
     state reducer / 条件边函数 / 纯函数

L1  节点契约测试    ——  Mock 掉 LLM，只验"节点返回的 dict 对不对"  ← 今天为零
     iter_node / synth_node / reflect_node / StatusToolNode

L2  图集成测试      ——  Mock 掉 LLM，验"整张图跑下来 state 对不对"   ← 今天为零
     完整 4 节点流 / 计数器累加 / 重置 / 死循环防护

L3  契约测试        ——  验"两个组件的接口对得上"                ← 今天为零（本轮 bug 全在这层）
     前端读的字段 vs 后端返回的字段 / API 响应体 schema

L4  端到端 + 评估   ——  真 LLM / 真 Milvus，分钟级，CI 里跑一次   ← 今天有一个但坏了
     12 case 路由评估 / 入库→检索→回答全链路
```

**关键认识**：本次发现的 3 个 bug **全部属于 L2/L3**，而这两层今天完全空白。
这不是"运气不好"，是**测试分层缺失的直接后果**——所以补测试要按层补，不是随便写几个用例。

---

## 2. 覆盖矩阵：v2.2 的 8 个核心机制现在测到了吗

| # | 机制 | 代码位置 | L0 | L1 | L2 | 现状 |
|---|---|---|---|---|---|---|
| M1 | `iter_count` 累加 / 重置 | `agent/state.py:31-33` | ❌ | ❌ | ❌ | **零覆盖** |
| M2 | `synth_count` 累加 / 重置 | `agent/state.py:37` | ❌ | ❌ | ❌ | **零覆盖** |
| M3 | `reflection_count` 只累加、永不重置 | `agent/state.py:41-43` | ❌ | ❌ | ❌ | **零覆盖** |
| M4 | `should_continue` 路由（tools/synth） | `agent/nodes/should_continue.py:10` | ❌ | ❌ | ❌ | **零覆盖** |
| M5 | `after_reflect` 路由（end/rewrite/re_iterate） | `agent/nodes/should_continue.py:30` | ❌ | ❌ | ❌ | **零覆盖** |
| M6 | `StatusToolNode` 4 种 status | `agent/nodes/status_tool_node.py` | ❌ | ❌ | ❌ | **零覆盖**，且**功能本身是坏的**（P0-0） |
| M7 | `reflect_node` 结构化输出 + 解析失败兜底 | `agent/nodes/reflect_node.py:97-105` | ❌ | ❌ | ❌ | **零覆盖**（v2.1 的覆盖已被删） |
| M8 | `tool_status` 合并 reducer | `agent/state.py:46-48` | ❌ | ❌ | ❌ | **零覆盖** |
| M9 | 完整 4 节点图连通性 | `agent/graph.py` | — | — | ❌ | **零覆盖** |
| M10 | 防死循环（timeout 不该判 re_iterate） | `agent/prompts/reflect_prompt.py:54` | ❌ | ❌ | ❌ | **零覆盖**（这是 v2.2 修的核心 bug 之一！） |
| M11 | `think` 块剥离 | `agent/llm_wrapper.py:29` | ❌ | ❌ | — | **零覆盖** |
| M12 | `strip_thinking` 的孤儿 `</think>` 分支 | `agent/llm_wrapper.py:50-52` | ❌ | — | — | **零覆盖** |
| M13 | `next_action` 持久化到 state | `agent/state.py`（**未声明**） | ❌ | ❌ | ❌ | **零覆盖**，且**字段本身缺失**（P1-1） |
| M14 | `MAX_SYNTH` 上限可达性 | `agent/constants.py:15` | ❌ | — | ❌ | **零覆盖**，且**上限不可达**（P1-0） |

**统计：14 个核心机制，0 个有测试。其中 3 个（M6 / M13 / M14）不只是没测，是功能本身有缺陷。**

---

## 3. 要补的测试文件（13 个，沿用 v2.2 plan 的命名）

> 命名沿用 `docs/superpowers/plans/2026-08-05-v2.2-graph-impl.md` 里已列的 13 个文件名，
> 这样 Makefile 的 `pytest test/test_v22_*.py` 不用改，**改完就能直接 `make test` 跑起来**。

### 🔴 3.0 最高优先级：先补 3 个能复现今天真 bug 的测试

在写任何用例之前，**先把这 3 个测试写出来并确认它们现在是红的**。
它们分别对应 `项目优化step1.md` 的 P0-0 / P1-1 / P1-2：

| 测试 | 断言 | 今天的状态 |
|---|---|---|
| `test_status_tool_node_writes_tool_status` | 跑一次含工具调用的图，断言 `state["tool_status"] == {"工具名": "success"}` | ❌ **红**（实际 `{}`）→ P0-0 |
| `test_next_action_persists_in_state` | 跑一次图，断言 `"next_action" in final_state` | ❌ **红**（实际没有）→ P1-1 |
| `test_rag_direct_page_field_matches_api` | 断言前端读的字段名 ∈ 后端 `ChatResponse` 字段名 | ❌ **红**（`answer` vs `response`）→ P1-2 |

> **这三个红测试就是本文档存在的意义。**
> 它们证明了"没测试"不是抽象风险，而是**已经漏掉了 3 个真 bug**。

> ⚠️ **Mock 注入的坑（踩过）**：
> `agent/nodes/__init__.py` 里 `from .reflect_node import reflect_node` 会让
> **包属性 `agent.nodes.reflect_node` 变成函数而不是模块**。
> 所以 `from agent.nodes import reflect_node` 拿到的是**函数**，
> 给它 `._get_llm = ...` 是给函数对象挂属性，**静默不生效**（测试会莫名其妙地调真 LLM）。
> 正确写法：
> ```python
> import importlib
> reflect_mod = importlib.import_module("agent.nodes.reflect_node")
> reflect_mod._get_llm = lambda: MockLLM()
> ```
> 实测：`type(import_module(...))` → `module` ✅；`type(from agent.nodes import ...)` → `function` ❌

### 3.1 `test/test_v22_state.py`（L0，8 用例）

纯函数，不需要任何 mock。

| 用例 | 断言 |
|---|---|
| `_reset_or_inc(None, 1)` | `1`（旧值为 None 时按 0 处理） |
| `_reset_or_inc(2, 1)` | `3`（累加） |
| `_reset_or_inc(5, 0)` | `0`（**0 = 显式重置**——这是 v2.2 的核心约定） |
| `_reset_or_inc(0, 0)` | `0` |
| `_inc_refl(2, 1)` | `3` |
| `_inc_refl(2, 0)` | `2`（**反思计数器不认 0 = 重置**——reflect 重置路径靠这个区分） |
| `_merge_tool_status({"a":"success"}, {"b":"timeout"})` | `{"a":"success","b":"timeout"}` |
| `_merge_tool_status(None, {"a":"success"})` | `{"a":"success"}` |

> ⚠️ **注意 M3 的坑**：`reflect_node` 在 `reflection_count >= MAX_REFL` 短路时返回 `"reflection_count": 1`（`reflect_node.py:73`），
> 对 `_inc_refl` 来说 `1` 是**累加 1**不是重置——所以短路后计数会继续涨。这正是 `docs/note/agent_note_05_reflection_audit.md` §3.2 记的"计数语义混合"。测试要把这个行为**固化下来**，或者修掉它并更新测试。

### 3.2 `test/test_v22_iter_node.py`（L1，8 用例）

Mock 注入点：`iter_node(state, llm=FakeLLM())`（`iter_node.py:32` 的 `llm=None` 形参）。

| 用例 | 断言 |
|---|---|
| 正常返回 AIMessage | 返回 dict 含 `messages=[AIMessage]` + `iter_count=1` |
| LLM 返回带 `tool_calls` 的 AIMessage | `messages[0].tool_calls` 非空（供 `should_continue` 用） |
| `iter_count >= MAX_ITER` | **不调 LLM**，返回 `content="已达迭代上限，结束"`，`iter_count=1` |
| LLM 抛异常 | 兜底返回 `AIMessage(content="READY")`，**不崩** |
| 返回 dict 的 key 集合 | 恰好是 `{"messages", "iter_count"}`（不多不少——防"写了不存在的 state 字段"） |
| `state["messages"]` 为空 | 不抛 `IndexError` |
| prompt 里带了 `iter_count` 和 `last_critique` | 断言构造出的 HumanMessage 内容包含对应值（防止 prompt 漏传状态） |
| `iter_count` 累加语义 | 返回 `iter_count=1`（不是 `iter_count+1`——累加由 reducer 做） |

### 3.3 `test/test_v22_synth_node.py`（L1，8 用例）

| 用例 | 断言 |
|---|---|
| `last_critique` 为空（首次模式） | prompt 含"【可用素材】"，不含"反思反馈"内容 |
| `last_critique` 非空（重写模式） | prompt 含 critique 原文 |
| `tool_status` 为空 | 渲染成 `"（无工具调用）"`（`synth_node.py:32`） |
| `tool_status` 有多个 | 每个工具一行 `- name: status` |
| 素材来自**最近一条** ToolMessage | messages 里放 2 条 ToolMessage，取最后一条 |
| LLM 抛异常 | 兜底 `"综合答案生成失败：{类型}"`，不崩 |
| `synth_count >= MAX_SYNTH` | **不调 LLM**，返回 `"已达综合上限，结束"` |
| 返回 key 集合 | `{"messages", "synth_count", "last_critique"}` |

### 3.4 `test/test_v22_reflect_node.py`（L1，10 用例）

**这是从 v2.1 `test_reflect.py` 继承来的、要重新写一遍的部分**（旧文件已删）。

Mock 注入点：`reflect_node(state, llm=FakeStructuredLLM())`。

| 用例 | 断言 |
|---|---|
| 返回 `ReflectOutput(is_sufficient=True, next_action="end")` | `next_action == "end"`，`last_critique == ""` |
| 返回 `next_action="rewrite"` | `next_action == "rewrite"`，且 **`iter_count=0` 且 `synth_count=0`**（重置） |
| 返回 `next_action="re_iterate"` | 同上，**两个计数器都重置** |
| LLM 抛异常 | 兜底 `next_action="rewrite"` + `critique="反思解析失败"`（**不崩**） |
| Pydantic 解析失败（返回 dict 而非对象） | 同上兜底 |
| `reflection_count >= MAX_REFL` | **不调 LLM**，强制 `next_action="end"` |
| `reflection_count` 为 `None` | 当 0 处理，不崩 |
| prompt 里带了 `tool_status` | 断言 HumanMessage 含 tool_status 序列化结果 |
| prompt 里带了 `last_critique`（历史反思） | 断言含上一轮 critique |
| `messages` 里有多条 AIMessage | `_extract_latest_answer` 取**最后一条** AIMessage 的内容 |

### 3.5 `test/test_v22_status_tool_node.py`（L1，6 用例）

`StatusToolNode` 包装的是 LangGraph 的 `ToolNode`，直接测需要构造带 `tool_calls` 的 AIMessage。

| 用例 | 断言 |
|---|---|
| 工具返回非空字符串 | `tool_status == {"工具名": "success"}` |
| 工具返回空字符串 | `tool_status == {"工具名": "empty"}` |
| 工具抛 `TimeoutError` | `tool_status == {"工具名": "timeout"}`，**且返回了 ToolMessage**（防图卡死） |
| 工具抛其他异常 | `tool_status == {"工具名": "error"}`，且有 ToolMessage |
| 最后一条消息没有 tool_calls | 返回 `{}`（不报错） |
| 多个工具并发 | 每个工具名一个 status 键（不互相覆盖） |

> 建议用一个 `@tool` 装饰的假工具，`side_effect` 可配置为返回/空/超时/异常。

> 🔴 **这组测试今天会全红**，因为 `StatusToolNode` 覆写的是 `__call__`，
> 而 LangGraph 调的是 `.invoke()`（`ToolNode` 是 `Runnable`，`add_node` 会原样保留并调 `invoke`）。
>
> **测法要点**：直接调 `node.invoke(state, config)` 也会抛
> `ValueError: Missing required config key 'N/A' for 'tools'`——因为 `ToolNode.invoke` 需要带 runtime 的 config。
> 所以这组测试有两个选择：
> - **A（推荐）**：走完整图测（`build_graph().invoke(...)`），由 LangGraph 提供 config
> - **B**：直接构造一个带 runtime 的 config 来测 `invoke`
>
> 修法见 `项目优化step1.md` §2 P0-0：把 `__call__` 改成 `invoke` 并透传 `config`。
> 实测改完后：正常工具 → `{'echo': 'success'}`；抛 `TimeoutError` → `{'boom': 'timeout'}`。

### 3.6 `test/test_v22_edges.py`（L0，8 用例）

两个条件边函数是纯函数，最好测。

| 用例 | 断言 |
|---|---|
| `should_continue` 消息带 tool_calls | `"tools"` |
| `should_continue` 无 tool_calls | `"synth"` |
| `should_continue` 且 `iter_count >= MAX_ITER` | `"synth"`（**兜底优先于 tool_calls**） |
| `should_continue` 消息是乱码/非 AIMessage | `"synth"` |
| `after_reflect` `next_action="end"` | `"__end__"` |
| `after_reflect` `next_action="rewrite"` | `"synth"` |
| `after_reflect` `next_action="re_iterate"` | `"iter"` |
| `after_reflect` 未知 action / 字段缺失 | `"__end__"`（兜底不崩） |

### 3.7 `test/test_v22_counters.py`（L2，10 用例）—— **最重要的一组**

> `docs/note/agent_note_05_reflection_audit.md` §3.4 明确写过：
> **"只测了节点直接返回值，没测 LangGraph reducer 累加后的最终 state"**——这组测试就是补这个洞。

用 `StateGraph` 跑真实 reducer，断言**最终 state 里的计数器值**：

| 用例 | 场景 | 断言 |
|---|---|---|
| iter 跑 3 次 | iter 连续 3 次都发 tool_call | iter 节点**恰好被调用 3 次**（`MAX_ITER=3`），第 4 次没被调用 |
| iter 上限由谁拦 | 同上 | 是 `should_continue` 在 `iter_count >= MAX_ITER` 时转 synth 拦下的（`should_continue.py:17`）——**不是** iter_node 自己的边界检查 |
| iter_node 边界分支 | 直接调 `iter_node(state, llm=Fake())`，`state["iter_count"] = MAX_ITER` | 返回 `"已达迭代上限，结束"` 且**不调 LLM**（防御性冗余分支，走图时不可达） |
| reflect 后重置 | reflect 返回 `iter_count=0, synth_count=0` | 最终 `iter_count == 0`，`synth_count == 0` |
| reflection 永不重置 | reflect 返回 `reflection_count=1` 连续 3 次 | 最终 `reflection_count == 3`，之后仍是 3 |
| 三计数器独立 | 只跑 iter | `synth_count == 0`，`reflection_count == 0`（**v2.1 混叠 bug 的回归测试**） |
| 三计数器独立 | 只跑 synth | `iter_count == 0`，`reflection_count == 0` |
| rewrite 循环 | reflect→rewrite→synth→reflect→end | `synth_count` 被重置后重新计（**注意当前语义见下条**） |
| **MAX_SYNTH 不可达** | reflect 永远返回 `rewrite` | 实测 synth 被调用 **4 次**、`synth_count` 终值 **1** → **`MAX_SYNTH=2` 一次都没触发**（对应 P1-0）。**这条测试要先固化现状，等语义拍板后再改断言** |
| MAX_REFL 兜底 | 同上 | 第 4 次 reflect 命中 `MAX_REFL` 短路 → 强制 end，**图必须终止**（实测 reflect 调用 3 次后短路，`reflection_count` 终值 4） |
| 计数器不串 | iter_count=2 时跑 synth | `iter_count` 仍是 2（synth 不污染 iter 计数） |

> **关于 `MAX_SYNTH` 不可达（P1-0）**：这条用例的价值在于**先把当前行为钉死**，
> 避免"拍板改语义"时不知道自己在改什么。语义拍板后（改 reset 策略 / 改判定位置），
> 这条断言要同步更新，并补一条"综合超过 N 次后强制 END"的用例。

### 3.8 `test/test_v22_tool_status.py`（L1+L2，8 用例）

| 用例 | 断言 |
|---|---|
| 单工具 success | `tool_status == {"rag_search": "success"}` |
| 多工具 | 两个键都在 |
| 后写覆盖先写（同名字） | 后写的值生效（merge 语义） |
| timeout 后 reflect 收到 tool_status | reflect 的 prompt 里含 `"timeout"` |
| **防死循环集成** | 工具 timeout → reflect 判 `re_iterate` → **图必须终止**（MAX_REFL 兜底） |
| **防死循环集成** | 工具 timeout → reflect 判 `end` → 立即终止 |
| `empty` 状态 | `tool_status == {"rag_search": "empty"}`，且 synth 拿到的是"无工具调用"以外的内容 |
| error 状态 | `tool_status == {"rag_search": "error"}` |

### 3.9 `test/test_v22_prompts.py`（L0，6 用例）

prompt 是"看不见的代码"，最容易被改坏。**用断言把关键约束钉死**：

| 用例 | 断言 |
|---|---|
| `ITER_PROMPT` 含 "READY" | 不调工具时的信号词存在 |
| `ITER_PROMPT` 含 "不要写答案" | **v2.1 双角色 bug 的回归防线** |
| `SYNTH_PROMPT` 含 4 种工具状态的处置 | 出现 "success" / "empty" / "timeout" / "error" 四个词 |
| `REFLECT_PROMPT` 含 `next_action` 三个取值 | `"end"` / `"rewrite"` / `"re_iterate"` 都在 |
| `REFLECT_PROMPT` 含防死循环硬约束 | 含 "timeout/error" + "re_iterate" 的约束句 |
| `REFLECT_PROMPT` 含评审者角色约束 | 含 "你是评审者，不是答题者" |

### 3.10 `test/test_v22_graph_integration.py`（L2，6 用例）

用假 LLM 跑完整图，断言**消息序列**和**最终 state**。

| 用例 | 场景 | 断言 |
|---|---|---|
| 不调工具路径 | iter→READY | 最终 messages 序列 = Human, AI(READY), AI(答案) |
| 调工具路径 | iter→tool_call→tools→iter→READY→synth | messages 含 ToolMessage |
| 工具→iter 回环 | 断言 iter 被调用了 2 次 |
| reflect 判 end | 最终 `next_action` 存在且为 end |
| reflect 判 rewrite | synth 被调用 2 次 |
| 图一定终止 | 任意 mock 组合下 `invoke` 都在有限步内返回（**加超时保护**） |

### 3.11 `test/test_v22_walkthrough.py`（L2，6 用例）

4 种**用户视角**的典型场景，模拟真实对话：

1. "你好" → 不调工具，直接答
2. "我的知识库里有什么" → 调 rag_search → 基于 chunk 答
3. "1+1 等于几" → 调 calculator → 用返回值答
4. 知识库里没有 → 诚实说"没找到"（**grounding 测试**）
5. 工具超时 → 诚实说"查询受限"（**诚实性测试**）
6. 反思要求补充 → 重写后答案包含 critique 要求的内容

### 3.12 `test/test_v22_regression_v21_bugs.py`（L2，9 用例）—— **面试讲点**

> 这组测试的意义不在覆盖率，在于**它证明了 v2.2 修的 3 个 bug 真的修好了**。
> 面试时这是最值钱的一组。

| # | v2.1 的 bug | 回归测试怎么写 |
|---|---|---|
| 1 | 节点层双角色（agent 节点既决策又写答案） | 断言 iter 节点**从不**产出最终答案（内容不含长文本答案），答案只由 synth 产出 |
| 2 | 计数器混叠（单 `iterations`） | 断言 3 个计数器**独立**（见 3.7） |
| 3 | 工具超时死循环 | 断言 timeout → re_iterate 场景下图**在有限步内终止** |
| 4 | 反思解析失败导致崩溃 | 断言 LLM 抛异常时 reflect 兜底不崩 |
| 5 | 反思短路计数语义 | 固化当前行为（或修掉后更新断言） |
| 6 | 工具状态丢失 | 断言 timeout/error 时仍写 ToolMessage |
| 7 | graph 卡在 tool_calls 未应答 | 断言异常路径下 ToolMessage 数量 = tool_call 数量 |
| 8 | `MAX_ITER` 边界 | 断言第 MAX_ITER+1 次不调 LLM |
| 9 | `MAX_SYNTH` 边界 | 断言超限后强制结束 |

### 3.13 `test/test_v22_eval_smoke.py`（L4，2 用例，`@pytest.mark.slow`）

真 LLM，只跑 2 个 case，防止 CI 每次跑全量 12 个（成本/时间）。

| 用例 | 断言 |
|---|---|
| T04（应走 rag） | `tool_called == True`，答案非空 |
| T03（应走 chat） | `tool_called == False`，答案非空 |

> Makefile 里已经有 `--ignore=test/test_v22_eval_smoke.py`，说明设计上就想把它从单测里排除。

---

## 4. RAG 侧测试（RAG 是 Agent 的工具，但链路独立）

### 4.1 `test/test_rag_retrieve.py`（L1/L3，新增）

| 用例 | 断言 |
|---|---|
| `RagModel.retrieve()` 返回 list[str] | 类型断言 |
| 无结果时返回空 list | 不抛异常 |
| `top_k` 参数生效 | 塞 10 个 chunk，检索 top_k=3 → 返回 ≤3 条 |
| **top_k 配置化后** | 改 YAML 生效（对应 P2-5） |
| 检索**失败**时 | 返回 `[]` 而不是抛异常（`rags.py:117-119` 的兜底） |
| **Milvus 未连接**时 | 返回 `[]` + warning 日志，不崩（`rags.py:95-97`） |

### 4.2 `test/test_rag_citation.py`（新增，依赖 P2-1 完成）

> **前置**：Milvus schema 加了 `source`/`chunk_id` 字段并重跑入库。没做之前这个测试写不了。

| 用例 | 断言 |
|---|---|
| `retrieve()` 返回的 chunk 带来源 | 返回结构从 `list[str]` 升级为 `list[dict]`（含 `text` + `source`） |
| `output_fields` 包含 source | 不再只有 `['text']`（`rags.py:108`） |
| 答案里出现 `[1]` 形式的引用 | 引用编号能对应回 chunk 编号 |
| 引用编号不越界 | 答案里的最大编号 ≤ 召回 chunk 数 |

### 4.3 `test/test_vector_split.py`（已有，扩）

现有 1 个用例（alias + 时间戳 collection）。建议补：

| 用例 | 断言 |
|---|---|
| 切分结果不为空 | `txt/` 有文件时，collection 行数 > 0 |
| alias 指向新 collection | 现有用例已覆盖 |
| 旧 collection **仍存在** | **可回滚性**——`vector_main.py` 承诺不删旧库 |
| chunk 不超长 | 每个 chunk 长度 ≤ chunk_size + overlap |
| 入库失败不中断整批 | 塞一个坏文件，其余仍入库（对应 P2-7） |

### 4.4 `test/test_embedding_consistency.py`（新增）

对应 P1-7（索引端 / 查询端两个 embedding 客户端）。

| 用例 | 断言 |
|---|---|
| 索引用客户端 vs 查询用客户端 | 对同一段文本，**两个客户端产出的向量一致**（或至少 cosine > 0.999） |
| 客户端统一后 | 只剩一个 embedding 入口（用 AST 或 monkeypatch 断言调用次数） |

---

## 5. L3 契约测试（这次 bug 的重灾区，强烈建议加）

**核心思想**：两个组件靠"字段名"通信时，**把字段名写进测试**。

### 5.1 `test/test_api_response_contract.py`（新增）

| 用例 | 断言 |
|---|---|
| `/rag` 返回体有 `response` 字段 | `api/api_rag.py:14-16` 的 `ChatResponse` 定义 |
| **`/chat` 返回体字段 = 前端 `rag_direct_page.py` 读的字段** | ❌ **今天就是这里错了** |
| `/agent/chat` 返回体有 `response` | `api/api_agent.py:22` |
| `/switch_model` 请求/响应 schema | `api/api_model.py:13` |
| `/api/upload-and-parse` 存在 | 路由挂载回归（现有 `test_main_routes_covered.py` 已覆盖 router 挂载，但没覆盖"字段名"） |

> **做法**：在 `web_page/*.py` 里把"读哪个字段"抽成常量，然后测试断言 **前端读的字段名 ∈ 后端 Pydantic 模型的字段名集合**。
> 这样以后谁改后端字段名，测试立刻红。

### 5.2 `test/test_api_e2e.py`（L4，`@pytest.mark.slow`）

用 FastAPI `TestClient` 打真实端点（不启 Milvus 也能测 chat/agent 的非检索路径）：

| 用例 | 断言 |
|---|---|
| `POST /chat` | 200 + 有 `response` 字段 |
| `POST /rag`（Milvus 未起） | 不 500（应该优雅降级） |
| `POST /agent/chat` | 200 + 有 `response` 字段 |
| `POST /agent/chat` 空 query | 422（Pydantic 校验） |
| `GET /debug/simple` | 200 + 含"当前模型" |
| `GET /available` | 200 + 列表含 `MiniMax-M3.1-Flash` |

---

## 6. 评估集（L4）：口径要诚实

### 6.1 12 个 case（`test/agent_test_cases.json`，现有）

| ID | query | 期望 | 类别 |
|---|---|---|---|
| T01 | 你是谁 | chat | general |
| T02 | 1+1等于多少 | chat | general |
| T03 | 你好 | chat | general |
| T04 | 在我的知识库里有什么内容 | rag | knowledge_lookup |
| T05 | 我之前上传的文档讲了什么 | rag | knowledge_lookup |
| T06 | RAG 的核心定义是什么 | rag | knowledge_lookup ← **唯一历史失败项** |
| T07 | Python 的 list 和 tuple 有什么区别 | chat | general |
| T08 | 你了解我最近读的书吗 | rag | knowledge_lookup |
| T09 | 上海今天天气怎么样 | chat | rag_empty（无天气工具） |
| T10 | 介绍下 LangGraph | chat | general |
| T11 | 我的简历里有什么 | rag | knowledge_lookup |
| T12 | 解释下什么是 ReAct 模式 | chat | general |

> ⚠️ **T09 已经是过时期望**——v2.2 加了 `weather` 工具，问天气**应该调工具**。
> 期望值还写着 chat，会造成假阴性。**评测集本身需要随代码更新**，这一点要在测试里体现。

### 6.2 评估指标该测什么

现在的 `run_agent_eval.py` **只测"选对工具没有"**（路由准确率）。这不够。至少要加三个维度：

| 维度 | 怎么算 | 为什么 |
|---|---|---|
| **路由准确率** | 选的工具 == 期望工具 | 现有指标 |
| **答案正确率** | `reference_keywords` 命中率 | `agent_test_cases.json` 里**已经有这个字段但没被用**！ |
| **引用正确率** | 答案里的引用编号能对应到 chunk | 需要 P2-1 完成后才有意义 |
| **稳定性** | 无异常率 | 现有指标 |

> **`reference_keywords` 字段是现成的宝藏**——`T01` 期望含"AI"/"助手"，`T02` 期望含"2"。
> 现在完全没用上。补上它，评估就从"选路对不对"升级到"答得对不对"。

### 6.3 必须修的（否则评估跑不起来）

```python
# test/run_agent_eval.py:84-85  —— 现在直接 ImportError
from agent.nodes import reflect as reflect_mod     # ❌ v2.2 改名 reflect_node
reflect_mod._llm = MockLLM()                        # ❌ v2.2 改成懒加载 _get_llm()

# 改成（注意用 importlib，见 §3.0 的坑）：
import importlib
reflect_mod = importlib.import_module("agent.nodes.reflect_node")
reflect_mod._get_llm = lambda: MockLLM()            # ✅ v2.2 的注入点

# test/run_agent_eval.py:71  —— 字段名过期，恒为 0
debug_result.get("iterations", 0)                   # ❌ v2.2 改名
debug_result.get("iter_count", 0)                   # ✅
```

> 🔴 **还有第 4 个必须修的**：`agent/runtime.py:91` 的
> `tool_called = bool(result.get("tool_status", {}))` —— 因为 P0-0，`tool_status` 恒为 `{}`，
> **`tool_called` 恒为 False**，12 个 case 会被全判成 "chat"。
> 修完 P0-0（`StatusToolNode` 改 `invoke`）后这条自动好。
>
> 修完之后**必须重跑评估**——因为
> **91.7% 是 v2.1 的数字**（那时靠"messages 里有没有 ToolMessage"判断，见脚本 docstring），
> **不是 v2.2 的成绩**。v2.2 的真实路由准确率目前是未知数。

### 6.4 还要补的评估：反思有效性 A/B（对应 P3-6）

> `docs/note/agent_note_05_reflection_audit.md` §4.2 原话：**"Mock 不是为了证明反思有效"**。

建议加一个 `test/run_reflect_ab.py`：

| 组 | 配置 | 对比指标 |
|---|---|---|
| A | 反思节点恒返回 `end`（等于关掉反思） | 12 case 的答案正确率 / 引用率 |
| B | 反思正常跑 | 同上 |
| **结论** | B > A 才算反思有效 | 否则就该诚实说"反思目前没有带来可测量的提升" |

**这个实验的价值**：无论结果好坏，都是面试里极好的素材——"我做了 A/B，结论是 X"。
比空口说"反思提升了质量"强 10 倍。

---

## 7. 执行顺序（务实版）

```
第 0 步（30 分钟）—— 🔴 先把 3 个红测试写出来（§3.0）
  □ test_status_tool_node_writes_tool_status   （今天红）
  □ test_next_action_persists_in_state         （今天红）
  □ test_rag_direct_page_field_matches_api     （今天红）
  → 确认它们是红的，这 3 条就是本次项目的"验收标准"

第 1 步（1 小时）—— 修 bug + 让"能跑"成立
  □ P0-0 StatusToolNode.__call__ → invoke（透传 config）  ← 功能性修复
  □ P0-2 修 run_agent_eval.py 的 import（importlib）+ 字段名
  □ P1-1 AgentState 加 next_action 字段
  □ P1-2 前端字段名改成 response
  □ P0-1 修 Makefile 指向
  □ 跑 pytest → 第 0 步那 3 个红测试变绿

第 1.5 步（30 分钟）—— 重跑 run_agent_eval.py，拿到 v2.2 的第一个真实准确率
  ⚠️ 别再用 91.7%（那是 v2.1 的）

第 2 步（半天）—— L0 纯逻辑，最便宜
  □ test_v22_state.py       (8)
  □ test_v22_edges.py       (8)
  □ test_v22_prompts.py     (6)
  → 此时 make test 已经比今天强 10 倍

第 3 步（半天）—— L1 节点契约
  □ test_v22_iter_node.py   (8)
  □ test_v22_synth_node.py  (8)
  □ test_v22_reflect_node.py (10)   ← 从 v2.1 删掉的那两个文件的精神恢复
  □ test_v22_status_tool_node.py (6)

第 4 步（1 天）—— L2 图集成（最容易暴露真 bug）
  □ test_v22_counters.py    (10)  ← 最重要
  □ test_v22_tool_status.py (8)
  □ test_v22_graph_integration.py (6)
  □ test_v22_walkthrough.py (6)
  □ test_v22_regression_v21_bugs.py (9)  ← 面试讲点

第 5 步（半天）—— L3 契约（防这次的 bug 复发）
  □ test_api_response_contract.py
  □ test_api_e2e.py (slow)

第 6 步 —— RAG 侧（依赖 P2-1）
  □ test_rag_retrieve.py
  □ test_rag_citation.py
  □ test_embedding_consistency.py

第 7 步 —— L4 评估
  □ 加 reference_keywords 命中判定
  □ 更新 T02 / T09 期望值（calculator / weather 工具已存在）
  □ 加 reflect A/B 脚本
```

---

## 8. CI / Makefile 建议

```makefile
# 单元测试（不依赖外部服务，CI 每次跑）
test-v22-unit:
	pytest test/test_v22_*.py test/test_main_routes_covered.py -v \
	       --ignore=test/test_v22_eval_smoke.py -m "not slow"

# 需要外部服务的（本地/手动跑）
test-v22-slow:
	pytest test/test_v22_*.py test/test_api_e2e.py -v -m "slow"

# 评估
test-v22-mock:
	PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py --mock
```

> **建议在 `pytest.ini` 里加 `markers = slow`**：
> ```ini
> markers =
>     slow: 需要真实 LLM / Milvus / 网络的测试
> ```

---

## 9. 面试口径（照着念，别超）

### 9.1 现在（今天，诚实版）
> "项目有 3 个 pytest 单测（路由挂载回归 + 向量化链路），和一套 12 case 的 Agent 路由评估脚本。
> 评估历史成绩是 v2.1 的 mock 91.7% / 真实 92%（T06 唯一错）。**v2.2 重构后我正在补单测，
> 目前 v2.2 的新单测还没落地**——这是我重构时删掉旧测试又没补回来的失误。"

### 9.2 补完第 4 步后（推荐目标）
> "v2.2 的 4 节点图、3 个独立计数器、工具 4 态状态机，都有单测覆盖；其中有一组是**回归测试**，
> 专门复现 v2.1 的 3 个 bug（节点双角色 / 计数器混叠 / 工具超时死循环），确认修好了。
> 评估是 12 case 的路由准确率 + 答案关键词命中率。"

### 9.3 绝对不要说
- ❌ "测试覆盖率 90%+" —— 没跑过覆盖率工具，别编
- ❌ "所有测试通过" —— 今天 `make test` 直接跑不起来
- ❌ "反思解决了幻觉问题" —— 反思对 T06 那个错例**没救回来**
- ❌ "工具超时死循环已修复" —— `StatusToolNode` 压根没生效（P0-0），reflect 收不到 timeout 信息
- ❌ 提 `test_reflect.py` / `test_reflection_count.py` —— **文件已删**，说错了很尴尬
- ❌ 拿 91.7% 当 v2.2 的成绩 —— **那是 v2.1 的数字**

### 9.4 值得主动说的（★ 最强素材）
> ✅ **"我补测试时发现，v2.2 我以为已经修好的工具超时死循环，其实没修好——
> `StatusToolNode` 覆写了 `__call__`，但 LangGraph 调的是 `invoke`，
> 所以工具状态从来没被记录过，reflect 收不到 timeout 信息，那条防死循环的硬约束是空的。
> **补测试的价值就在这儿：它把'我以为修好了'变成了'我验证过修好了'。**"

这句话同时展示：① 会读框架源码 ② 会写最小复现 ③ 有自我怀疑的工程习惯。
比罗列"我做了反思 / 混合检索 / rerank"强得多——因为**这些恰恰是你现在还没有的**。

> ✅ "v2.1 → v2.2 重构时我把旧测试删了但没补新的，这是流程上的失误。
> 我的教训是：**重构和测试必须同一个 PR**，删测试要和新测试一起提。"

> ✅ "我做过 A/B：开反思 vs 关反思，同一批 case 对比。结论是 ___。"
> （做完第 7 步就能填这个空）

---

## 10. 附：与现有文档的关系

| 文档 | 状态 |
|---|---|
| `docs/personal/项目测试面试准备.md` | ❌ **已过期**——通篇讲 `test_reflect.py` / `test_reflection_count.py`（已删）。修完本文档后应重写或标注废弃 |
| `docs/note/model_switch_2026_11_10.md` §3 | ✅ §3.1/3.2 就是本文档 P0-1/P0-2，§3.4（`with_structured_output` 在 M2.7/M3 失败）是环境约束，不是代码 bug |
| `docs/superpowers/plans/2026-08-05-v2.2-graph-impl.md` | ✅ 本文档的 13 个文件名沿用它的设计，只是当时**列了计划没写** |
| `docs/note/agent_note_05_reflection_audit.md` §4-5 | ✅ 本文档 L2/L3 层的原始需求来源（"只测了节点直接返回值，没测 reducer 累加后的 state"） |

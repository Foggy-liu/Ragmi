# RAGMI 测试体系设计（v2 · 自审修订版）

> **日期**：2026-11-16
> **分支**：`agent-v2.2-graph-refactor`
> **状态**：待用户审阅
> **替代**：`docs/plan/test-plan-l0-l4.md`（2026-11-10 版，写在纸上但从未执行；且其 §3.5/§3.7 仍按已被删除的 `StatusToolNode` 与 `MAX_SYNTH` 描述，已过时）
>
> **本文回答的问题**：给 RAGMI 做一套**能跑、能进 CI、覆盖真实流程**的测试，具体测什么、怎么造假、怎么落地。
>
> **v2 修订说明**：v1 设计做了一轮**代码级自审**（逐条核对到文件行号），发现 1 个致命方案错误、
> 3 个必然失败的硬断言、8 处"测了等于没测"的空覆盖、8 处未声明的隔离/flaky 风险。
> 修订清单见 **§11**。

---

## §1 背景与目标

### §1.1 现状（2026-11-16 实测）

| 维度 | 实测结果 |
|---|---|
| pytest 用例 | 13 个快用例（`test_agent_timeout.py` 11 + `test_main_routes_covered.py` 2），3.8 秒 |
| Agent 图逻辑覆盖 | **零** —— 没有任何用例跑 `graph.invoke()` |
| 浏览器端覆盖 | **零** —— 前端 3 个页面 0 个 E2E |
| e2e 验收用例 | `test_vector_split.py` 1 个，**25 分 29 秒**（每次全量重 embed 1667 块） |
| 探针 | 3 个手动脚本，发现的 2 个 bug 修完之后**没变成用例** |

### §1.2 目标

1. **把"流程走不走得通"变成可自动验证的东西** —— 工具调用成功 / 返回空 / 超时 / 失败，各会发生什么。
2. **补上浏览器层** —— 页面能不能用、接口字段对不对、已知 bug 有没有被固化。
3. **一条命令能跑完** —— 快的秒级回归 + 慢的真实环境冒烟，用 marker 区分。

### §1.3 非目标（明确不做）

- ❌ 不做 L0 白盒单测（reducer 内部实现、prompt 文本断言）—— 计数器语义改从图的外层观测点断言
- ❌ 不重写 `test/archive/scripts/` 里的 8 个归档脚本
- ❌ 不建 CI workflow（仓库目前无 CI 平台配置）—— 但**所有用例必须能在本地一条命令跑通**
- ❌ 不测还没写的功能（⚙ 模型配置按钮、session_id 多轮记忆）
- ❌ 不做视觉回归截图对比
- ❌ **不改 `agent/` 业务代码**
- ❌ 不修 P1-1（`/rag` 前端读 `answer`、后端返 `response`）—— 用 `xfail` 固化，等用户另行拍板
- ❌ **不测 reflect prompt 的"工具失败时不判 re_iterate"硬约束** —— 这只能由真 LLM 判定，见 §4.4 S4

---

## §2 分层架构

```text
┌────────────────────────────────────────────────────────────────────────┐
│ L4 浏览器 E2E        test/e2e/test_browser_e2e.py                      │
│   测「页面渲染对不对」  Playwright → Streamlit 三页面                   │
│   主体 = conftest 起「假后端」进程，Streamlit 经 API_BASE_URL 打到它   │
│   + 1 条真联调冒烟（真后端 + 真 MiniMax）                                │
├────────────────────────────────────────────────────────────────────────┤
│ L3 API 契约 + 上传逻辑 test/test_api_contract.py                       │
│   测「字段对不对 + 校验逻辑对不对」  FastAPI TestClient，patch 掉 ask  │
├────────────────────────────────────────────────────────────────────────┤
│ L2 Agent 流程        test/test_agent_flow.py              ← 核心        │
│   测「流程走不走得通」  假 LLM + 假向量库；真图 + 真工具 + 真异常归一化   │
│   成功 / 空 / 超时 / 失败 / 崩溃 / 死循环 / 上限 / 三种超时时机           │
├────────────────────────────────────────────────────────────────────────┤
│ L4 真环境冒烟        test/test_eval_smoke.py              (slow)       │
│   测「真链路还活着」    真 MiniMax + 真 Milvus，3~4 条                   │
└────────────────────────────────────────────────────────────────────────┘
```

**分层依据**：越往下越便宜越该多写，越往上越贵越该少写。L2 覆盖了 `docs/status/项目现状.md` §8 **P0-2**（Agent 图逻辑零 pytest 覆盖）；L4 浏览器层是当前最大的空白。

> ⚠️ **L4 的拦截机制不是 Playwright 的 `page.route()`** —— 原因见 §3.4，这是 v1 设计里唯一的致命错误。

---

## §3 关键技术决策

### §3.1 假 LLM 的注入点

| 方案 | 做法 | 取舍 |
|---|---|---|
| a | patch 3 个节点模块的 `_get_llm()` | 最简单，但**绕过 `ThinkingStripRunnable`** → think 剥离这层真实代码在测试里从未被执行 |
| **b（采纳）** | patch `LLMmodel.create_minimax()` → 返回假 chat 实例 | **think 剥离照常跑**（`ThinkingStripRunnable` 仍在链上）；假件多写约 20 行 |
| c | 只测节点不测图 | 测不到路由，不满足目标 1 |

**采纳 b**。理由：测试要证明的是"真实代码路径能跑通"，方案 a 会让 `ThinkingStripRunnable` 变成事实上的死代码，而它正是 v2.2 修 think 污染的关键一环。

> **核实过的前提**：`agent/graph.py` 全文**没有任何 LLM 构造** —— `build_graph()` 只做 `ToolNode(ALL_TOOLS, wrap_tool_call=status_wrapper)` + 节点注册。
> LLM 是在**节点 invoke 期**由 `_get_llm()` 懒加载的。所以：
> - `agent/runtime.py:28` 的 `_graph` 全局单例**不会**缓存住旧 LLM → patch 在 invoke 期生效 ✅
> - 因此**不需要**每次测试重建图（重建会额外拖慢）
> - 但**必须**在 spec 里写明这一点，否则实现者会误以为"图缓存了，patch 没用"而去改 `_get_graph()`，引入新的耦合

### §3.2 假 LLM 的形态

`agent/nodes/*.py` 里三处调用点（**已核对代码**）：

| 节点 | 代码 | 假件需要提供 |
|---|---|---|
| iter | `ThinkingStripRunnable(llm_instance.chat.bind_tools(ALL_TOOLS))` | `chat.bind_tools(tools)` → 返回一个 `.invoke()` 出 AIMessage 的对象 |
| synth | `ThinkingStripRunnable(llm_instance.chat)` | `chat.invoke()` → AIMessage |
| reflect | `ThinkingStripRunnable(llm_instance.chat.with_structured_output(ReflectOutput))` | `chat.with_structured_output(schema)` → 返回一个 `.invoke()` 出 `ReflectOutput` 的对象 |

**角色判定靠调用位置，不靠看 prompt** —— `bind_tools` 只有 iter 调、`with_structured_output` 只有 reflect 调、裸 `chat.invoke` 只有 synth 调。

```python
class FakeChat:
    def __init__(self, script):
        self.script = script
        self.calls = []          # 记录每次 invoke 的 (role, prompt_messages) —— 供 grounding 断言用

    def invoke(self, messages):                  # synth
        self.calls.append(("synth", messages))
        return self.script.play("synth", messages)
    def bind_tools(self, tools):                 # iter
        return _RoleView(self, "iter")
    def with_structured_output(self, schema):    # reflect
        return _RoleView(self, "reflect")
```

**剧本（Script）**：每个角色一条列表，依次出牌，**用完后重复最后一项**（这样"恒返回 `re_iterate`"可以一行表达）。列表元素可以是正常返回值，也可以是**要抛出的异常实例**。

```python
Script(
    iter=[AIMessage(content="", tool_calls=[{"name": "rag_search", "args": {"query": "x"}, "id": "call_1"}])],
    synth=[AIMessage(content="基于检索片段的答案")],
    reflect=[ReflectOutput(is_sufficient=True, critique="", next_action="end")],
)
```

> ⚠️ **D16 坑**：不要写 `from agent.nodes import iter_node` —— 那是函数不是模块。要用 `importlib.import_module("agent.nodes.iter_node")`。
> 本方案 patch 的是 `utils.models.model_setting.LLMmodel.create_minimax`，不涉及这个坑，但写其它 patch 时仍需注意。

> ⚠️ **`FakeChat.calls` 是必需字段**，不是可选的调试辅助 —— F1c（grounding 断言）依赖它。
> 假件必须**记录收到的 prompt**，否则无法验证"工具结果真的流到了综合节点"。

### §3.3 工具怎么造假

**不替换工具本身，只替换它下面那一层。**

```python
# patch agent.tools.rag_tool._ensure_rag → 返回 FakeRag
class FakeRag:
    def retrieve(self, query, top_k=5):
        # 可配置：返回 chunks / 返回 [] / 抛 RuntimeError / 睡 N 秒
```

这样**真实的部分**全部保留：`rag_search` 工具本体 → `Timer(TOOL_TIMEOUT)` 计时 → 异常归一化（`RuntimeError` → `AgentToolError`）→ `status_wrapper` 的 4 态分类 → ToolMessage 写入 → reflect 收到状态 → 路由。

**超时加速**：`rag_tool.py:13` 是 `from agent.constants import TOOL_TIMEOUT` 的模块级绑定，`rag_tool.py:58` 是 `Timer(TOOL_TIMEOUT).call(...)` —— **显式传参**，所以 patch `agent.tools.rag_tool.TOOL_TIMEOUT = 0.05` 即可把 30 秒压到 50 毫秒。

> 不会触发 `agent/constants.py` 的 `assert TOOL_TIMEOUT >= 1`（那个 assert 只在 import 时跑一次，而我们改的是 `rag_tool` 里的绑定）。

> 为什么不换掉整个工具：换掉就等于把 `Timer`、异常归一化、`status_wrapper` 这三段**最该被测的代码**排除在测试之外，等于什么都没测。

### §3.4 E2E 怎么拦后端 —— **不用 `page.route()`**

**v1 设计的致命错误**：v1 说"`page.route()` 在网络层、DNS 解析之前拦截"，并据此把 E1–E5 全部设计成浏览器拦截。**这个前提在本项目不成立。**

三个页面的后端调用**全部发生在 Streamlit 服务端进程里**：

| 文件 | 行 | 代码 |
|---|---|---|
| `web_page/rag_page.py` | 37-41 | `requests.post(url="http://localhost:8000/agent/chat", ...)` |
| `web_page/rag_direct_page.py` | 27-33 | `requests.post(f"{API_BASE}/rag", ...)` |
| `web_page/repo_admin.py` | 35-36 | `requests.post(f"{API_BASE}/api/batch-upload-and-parse", ...)` |

Playwright 的 `page.route()` 拦截的是**浏览器进程**发出的请求。Streamlit 服务端发出的请求**根本不经过浏览器** → **E1/E2/E3/E4/E5 一个都拦不到**。

**采纳方案：进程外假后端**

```text
┌──────────────┐  浏览器协议  ┌────────────────┐  HTTP  ┌──────────────────┐
│  Playwright  │ ───────────► │ Streamlit(8511)│ ─────► │ 假后端(conftest) │
│  (Chromium)  │ ◄─────────── │  API_BASE_URL= │ ◄───── │ 127.0.0.1:<port> │
└──────────────┘   websocket  │  假后端地址     │  固定  └──────────────────┘
└─────────────────────────────────────────────────────────────────┘
```

1. conftest 用 `http.server.ThreadingHTTPServer` 起一个假后端，实现
   `/agent/chat`、`/rag`、`/api/batch-upload-and-parse` 三个路由
2. conftest 起 Streamlit 时注入 `API_BASE_URL=http://127.0.0.1:<假后端端口>`
3. 前端三个文件改成读 `API_BASE_URL`（§5.1）→ Streamlit 的 `requests.post` 就打到假后端
4. 假后端可按用例脚本返回：正常 / 500 / 缺字段 / 空响应 / 慢响应

> **推论（必须写进 §5.1）**：改前端地址 **不是"顺手修 P1-5"**，而是 **E2E 可测性的前提**。
> 不改，浏览器层一条用例都跑不起来。

> **推论（必须写进 §5.5）**：E2E **不能复用用户已开的 Streamlit** —— 复用来的进程没有
> `API_BASE_URL` 注入，拦截失效。E2E 必须每次起**自己的** Streamlit（专用端口 8511）。

### §3.5 假后端的响应体必须镜像真实契约

v1 没规定 mock 的响应体形状 → 这是最容易让 E2E"绿得莫名其妙"的地方。**实测真实后端契约**：

| 端点 | 真实响应体 | 来源 |
|---|---|---|
| `POST /agent/chat` | `{"response": "<答案>"}` | `api/api_agent.py:22-24, 39` |
| `POST /rag` | `{"response": "<答案>"}` | `api/api_rag.py:16, 22` |
| `POST /chat` | `{"response": "<答案>"}` | `api/api_chat.py:16, 18` |
| `POST /api/batch-upload-and-parse` | `{"status","message","upload_details":{"uploaded_files","skipped_files","failed_uploads"},"parse_results","note"}` | `api/api_file.py:115-134` |

**硬规则**：

- 假后端给 `/rag` 必须返回 `{"response": ...}`。若误返回 `{"answer": ...}`，
  前端 `rag_direct_page.py:33` 的 `.get("answer")` 就会拿到值 → **E4 的 `xfail(strict=True)` 会 XPASS → 报失败**
- 假后端给 `/agent/chat` 必须返回 `{"response": ...}`。若返回 `{"answer": ...}`，
  `rag_page.py:44` 的 `result["response"]` 会 **KeyError** → 页面显示"请求失败：'response'" → E1 假红
- 假后端给上传端点必须返回带 `upload_details.uploaded_files` 的结构，否则 `repo_admin.py:44` KeyError

### §3.6 隔离规则（v1 未声明，是 flaky 的主要来源）

| # | 规则 | 原因 |
|---|---|---|
| 1 | **`import main` 必须写在测试模块顶层**（collection 期完成），不能写在 fixture 里 | `main.py:63` 在**模块级**调 `LLMmodel.create_minimax()`；`main.py:59-60` 模块级建 `ModelManager()`。若 patch 之后才 import main，`main` 的默认模型会变成假件 → `/chat` `/rag` 路由**拿假 LLM 回答** → C2/C3 变成"对着假件测假件" |
| 2 | **patch 只在 L2 的用例里用**，L3 用例不得 patch `LLMmodel.create_minimax` | 同上 |
| 3 | **C7 测完必须还原模型** | `api/api_model.py:27` 的 `switch_model` 改的是**进程全局**模型；不还原会污染后续 `/chat` `/rag` 用例 |
| 4 | **L2 用例直接 `graph.invoke()`，不用 `runtime.ask()`（除非要断言 5 字段契约）** | `runtime.py:95` 写死 `deadline = time.time() + TOTAL_TIMEOUT(90)`，测试无法控制超时时机 → F9 必须自己 invoke 图并传自定义 `deadline` |
| 5 | **E2E 每次起自己的 Streamlit（8511 端口 + 注入 env），不复用** | 见 §3.4 推论 |

### §3.7 已知 bug 的处理：`xfail(strict=True)`

P1-1（`/rag` 前端读 `answer`、后端返 `response` → 页面永远显示「(无答案)」）**这一轮不修**。

用 `xfail(strict=True, reason="P1-1: ...")` 标记：

- 现在：报 `xfailed`，不算失败 ✅
- 将来有人修好 P1-1：测试变成 `XPASS`，`strict=True` 让它**报失败** → 逼着清理标记

这是"把债可视化"，比直接断言 `== "(无答案)"`（把 bug 固化成期望）好。

> 前提：假后端必须返回真实契约 `{"response": ...}`（§3.5），否则会意外 XPASS。

---

## §4 用例清单

### §4.1 L2 流程测试 `test/test_agent_flow.py`

> 所有用例都**直接 `graph.invoke()`**（除 F11 显式测 `ask()` 契约），
> 以便控制 `deadline`、观察 `state` 全部字段。

| # | 场景 | 造法 | 断言 |
|---|---|---|---|
| F1 | 工具成功 | 假 rag 返回 2 段 chunk | `tool_status` 有 1 条 `status=success`/`code=OK`/`retryable=false`；ToolMessage 内容 == `"\n\n---\n\n".join(chunks)`（**拼接串，不是 chunk 列表**）；答案非空 |
| **F1c** | **grounding：工具结果真的流到了综合节点** | 同 F1 | 假件记录的 **synth 那次 prompt 全文**中**包含 chunk 原文**。没有这一条，F1 的"答案非空"是恒真断言 |
| F1b | 同轮并发调同一工具 2 次 | 假 iter 发 2 个同工具 tool_calls | `set(tool_status.keys()) == {发出去的两个 tool_call id}` —— **key 必须等于调用 id**，不是工具名；且两条状态都存在、互不覆盖 |
| F2 | 工具返回空 | 假 rag 返回 `[]` | `status=empty`/`code=EMPTY_RESULT`/`retryable=false`；**ToolMessage 内容是空字符串**（不是中文兜底串 —— 这是 v2.2 的关键修复，见 `rag_tool.py:52-54`） |
| F3 | **工具超时** | 假 rag 睡 0.2s > `TOOL_TIMEOUT(0.05)` | `status=timeout`/`code=TOOL_TIMEOUT`/`retryable=true`；ToolMessage 内容 `json.loads` 后 `code=="TOOL_TIMEOUT"`、`retryable==true`；**图走完不崩**；答案非空 |
| F4 | **工具失败** | 假 rag 抛 `RuntimeError` | `status=error`/`code=TOOL_ERROR`/`retryable=false`；ToolMessage 内容 `json.loads` 后 `code=="TOOL_ERROR"`；图走完不崩 |
| F5 | LLM 崩（iter） | 假 iter 抛异常 | 兜底 `"READY"` → synth 仍出答案；不崩；**且 `ask()` 返回的答案 ≠ `"READY"`** |
| F6 | 反思解析失败 | 假 reflect 抛异常 | `last_critique="反思解析失败"`；`reflection_count=4`；**终态 `next_action="end"`**（第 4 次进 reflect 撞 `MAX_REFL` 强制 end，不调 LLM）；reflect LLM 只调 3 次；不崩 |
| F7 | **死循环防护** | 假 reflect 恒返回 `re_iterate` | reflect 节点**进入 4 次**，其中**只有 3 次 LLM 调用**（第 4 次撞 `reflection_count >= MAX_REFL` 直接 end，不调 LLM）；`reflection_count` 终值 == **4**；总步数 < `RECURSION_LIMIT(42)` |
| F8 | 工具循环上限 | 假 iter 每次都发 tool_calls | iter 节点**进入 3 次**，其中**只有 2 次 LLM 调用**（第 3 次撞 `iter_count + 1 >= MAX_ITER` 返回"已达迭代上限，结束"）；`iter_count` 终值 == **3**；**无悬空 tool_calls** |
| **F9a** | **总时限：进 iter 前就过期** | `deadline = time.time() - 1` | iter 短路 → `expired=True` → `should_continue` 走 `"__end__"` → **synth 从未执行**。当前实现下 `ask()` 返回的是**内部占位** `"已达总时限，停止思考"`。用 `xfail(strict=True)` 标记"期望返回友好提示，实际返回内部占位" |
| **F9b** | **总时限：synth 前过期** | `deadline = now + 0.05`，假 iter 睡 0.2s | synth 短路 → 消息内容 == `"回答超时：思考时间超过总时限"`；`last_answer` 为空串；图终止 |
| **F9c** | **总时限：reflect 时过期** | `deadline = now + 0.05`，假 synth 睡 0.2s | reflect 撞 `is_expired` → `next_action=end`；答案 == synth 写出的正常答案；图终止 |
| **F10** | **兜底路由分支** | 假 reflect 返回 `next_action="unknown"` | `after_reflect` 走 `"__end__"`（`should_continue.py:51-52`）；不崩 |
| **F11** | **`ask()` 返回契约** | 正常成功一次 | debug=True 返回**恰好 5 个键**：`answer`/`iter_count`/`reflection_count`/`tool_called`/`last_action`；且 `answer` **不是任何内部占位**（`"READY"` / `"已达迭代上限，结束"` / `"已达总时限，停止思考"`） |

**公共不变式（参数化套在 F1–F10 上）**：

> 每个 `tool_call` 都有对应的 `ToolMessage` —— **悬空数 == 0**

这是 v2.2 修过的 bug（悬空 tool_calls 让 MiniMax 报 HTTP 400）的回归护栏。

### §4.2 L3 API 契约 + 上传逻辑 `test/test_api_contract.py`

用 `fastapi.testclient.TestClient`，patch `api.api_agent.ask` → 零成本、不碰真 LLM。

> ⚠️ **TestClient 必须用 `with TestClient(app) as client:`** —— 否则 lifespan 不跑，
> `app.state.model_manager` 不存在 → `/chat` `/rag` 依赖注入失败 → 500。

| # | 断言 |
|---|---|
| C1 | `POST /agent/chat` → 200，body **恰好**含 `response`（且**不含** `answer`） |
| C2 | `POST /rag` → 200，body 含 `response` |
| C3 | `POST /chat` → 200，body 含 `response` |
| **C4** | `POST /agent/chat` **缺 `query` 字段** → 422。⚠️ **空串 `{"query": ""}` → 200**（`api_agent.py:18` 的 `Field(...)` 没有 `min_length`）—— v1 设计在此处写反了 |
| C5 | `GET /debug/simple` → 200 |
| C6 | `GET /available` → 200，`available_models` 含 `{"platform":"minimax","model_name":"MiniMax-M3.1-Flash"}`（实测共 11 个模型） |
| C7 | `POST /switch_model` → 成功时 `{"success": true, "current_model": {...}}`；失败时 `{"success": false, "message": ...}`。**测完必须还原模型**（§3.6 规则 3） |
| **C8** | `POST /api/batch-upload-and-parse` **路径穿越** → 文件名 `"../../evil.txt"` 落进 `failed_uploads` 且 `reason` 含"非法路径"；`documents/` 外**没有**产生文件 |
| **C9** | `POST /api/batch-upload-and-parse` **类型白名单** → `".exe"` 落进 `failed_uploads` 且 `reason` 含"不支持的文件类型"（`api_file.py:67-73`） |
| **C10** | `POST /api/batch-upload-and-parse` **同名跳过 / overwrite** → 同名文件第二次上传（`overwrite=false`）落进 `skipped_files`；`overwrite=true` 时落进 `uploaded_files` 且 `status=="覆盖"`（`api_file.py:75-86`） |

> C8–C10 测的是**后端上传逻辑本身**（全项目最适合单测、零外部依赖、有真实业务语义的代码）。
> v1 设计把这块整个漏了 —— E5 走假后端，后端上传逻辑**一行都测不到**。
> ⚠️ C8–C10 会调用 `txt_main()` 全量扫 `documents/` → 用唯一文件名 + 测完清理。

### §4.3 L4 浏览器 E2E `test/e2e/test_browser_e2e.py`

**主体**：conftest 假后端（§3.4）+ 专用 Streamlit（8511 端口，注入 `API_BASE_URL`）。
**选择器均为 2026-11-16 实测得来**（非猜测）。

| # | 页面 | 用例 | 选择器 |
|---|---|---|---|
| E1 | 智能问答 | 发问 → 出现用户消息 + 助手答案 | `[data-testid="stChatInputTextArea"]` → `press("Enter")`；`[data-testid="stChatMessage"]` 计数 = 2；`img[alt="assistant avatar"]` 之后的 content 非空 |
| E2 | 智能问答 | 🗑 清空 → 消息归零 | `button:has-text("🗑")` |
| E3 | 智能问答 | ⚙ 点击**不报错**（功能未实现，只断言不崩） | `button:has-text("⚙")` |
| E4 | 知识库问答 | 发问 → **预期「(无答案)」**（P1-1 固化） | `xfail(strict=True)`；假后端**必须**返回 `{"response": ...}`（§3.5） |
| E5 | 仓库管理 | 选文件 → 上传并解析 → 出统计 | `input[data-testid="stFileUploaderDropzoneInput"]` + `button:has-text("上传并解析")`；断言**文本** `完成：` 出现 **且** 数量 **> 0**（只断言"完成："是恒真的，见 §11 D-10） |
| E6 | 菜单 | 三页互切 | `page.frame_locator('iframe[src*="streamlit_antd_components"]').get_by_text("知识库问答").click()` |
| E7 | 智能问答 | **后端返回 500** → 页面显示"请求失败"，**不白屏** | 假后端返 500；断言页面含"请求失败"且无 `[data-testid="stException"]` |
| E8 | 智能问答 | **真联调冒烟**（不拦截，真后端真 LLM） | 同 E1，超时给 90 秒 |

E1–E7 走假后端；E8 单独起真链路（真 Streamlit 指向真后端 8000，或直接用 `runtime.ask()`）。

### §4.4 L4 真环境冒烟 `test/test_eval_smoke.py`（slow）

| # | case | 断言 |
|---|---|---|
| S1 | "1+1等于多少" | `tool_called=True`；答案非空且含 "2" |
| S2 | "你好" | 答案非空 |
| S3 | "我的知识库里有什么内容" | `tool_called=True`（走 rag_search） |
| **S4** | **"工具失败后 reflect 会不会判 re_iterate"** | 真 LLM 触发一次工具失败 → 断言图**终止**且 `reflection_count` 不打满。⚠️ 这条**天然 flaky**（LLM 决策随机）→ 只断言"不失控"，不断言具体 `next_action` |

用 `runtime.ask(debug=True)`，断言 5 字段齐全。

> ⚠️ **S1–S3 已知会 flaky**：v2.2 实测路由准确率 83.3%，失败项是 T06（该检索没检索）
> 和 T10（不该检索却检索 3 轮，单 case 106 秒）。S3 属于"该检索"类 → **有概率失败**。
> 标 `slow` + 默认不跑 + 失败时打印实际工具名，便于人工判断是"回归"还是"LLM 波动"。

---

## §5 改动清单

### §5.1 业务代码（唯一一处，3 个文件各 1~2 行）

```python
# web_page/rag_direct_page.py / web_page/repo_admin.py
import os
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
```

```python
# web_page/rag_page.py —— ⚠️ 此文件当前【没有】API_BASE 变量，
# 只有 requests.post(url="http://localhost:8000/agent/chat") 一处硬编码。
# 改法是【改那一行】，不是"新建一个 API_BASE 变量然后忘了改 url"：
import os
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
...
    response = requests.post(
        url=f"{API_BASE}/agent/chat",
        json={"query": query},
        timeout=60
    )
```

- 本地裸跑 → 用默认值 `http://localhost:8000` ✅
- docker-compose → **已有**的 `API_BASE_URL: http://api:8000` 复活 ✅（它目前是死配置，前端根本没读）
- **E2E → conftest 注入 `API_BASE_URL` 指向假后端**（§3.4）—— **这是浏览器层能测的前提**

**副作用**：顺带修掉 §8 **P1-5**（API 地址三套并存）。

### §5.2 依赖

`requirements-dev.txt` 加 `pytest-playwright`（自带 `page` fixture、`expect` 自动重试、失败留 trace/video/screenshot）。

> 现状实测：环境里已有 `playwright 1.58.0` + `chromium-1217` 浏览器二进制 ✅；
> 缺的是 `pytest-playwright` 这个 pytest 插件。

### §5.3 pytest 配置

```ini
markers =
    slow: 需要真实 LLM / Milvus / 网络
    e2e: 需要浏览器 + 本地服务
```

并给 `test/test_vector_split.py` 加 `@pytest.mark.slow` —— 它现在混在默认流程里，**让 `pytest` 每次要跑 25 分钟**（实测）。

### §5.4 新增文件

| 文件 | 内容 |
|---|---|
| `test/conftest.py` | 假 LLM（Script/FakeChat）、假 RagModel、**假后端 HTTP 服务**、Streamlit/uvicorn 启停 |
| `test/test_agent_flow.py` | F1–F11 + 公共不变式 |
| `test/test_api_contract.py` | C1–C10 |
| `test/test_eval_smoke.py` | S1–S4（slow） |
| `test/e2e/test_browser_e2e.py` | E1–E8（e2e） |

### §5.5 服务拉起策略（按用途分开，v1 混成一套是错的）

| 用途 | 策略 | 理由 |
|---|---|---|
| **L2 / L3 快回归** | **不起任何服务** | 假 LLM + 假 rag + TestClient，全部进程内 |
| **E2E 浏览器** | **每次起自己的**：假后端（随机端口）+ Streamlit（**8511**，注入 `API_BASE_URL`）→ 测完只杀自己起的 | 复用用户已开的 Streamlit 会丢掉 env 注入 → 拦截失效（§3.4） |
| **真联调 E8 / slow 冒烟** | 复用真后端 8000（探活 `/debug/simple`），没有才 spawn uvicorn | 真链路贵，尽量复用用户已在跑的服务 |

---

## §6 Streamlit + Playwright 已知坑（实测得出）

| # | 坑 | 应对 |
|---|---|---|
| 1 | 首屏要等整个 Streamlit 脚本跑完才出内容 | `expect(page.locator('[data-testid="stChatInput"]')).to_be_visible(timeout=60000)` |
| 2 | `st.rerun()` 后 DOM 整体重建 | 断言用 `expect(...).to_have_count(n, timeout=...)`，不要一次性 `count()` |
| 3 | **`sac.menu` 在 iframe 里** | `page.frame_locator('iframe[src*="streamlit_antd_components"]').get_by_text("知识库问答").click()` |
| 4 | 菜单项文本**前面带图标字符**（`" 知识库问答"`） | 用子串匹配 `get_by_text("知识库问答")`，不要精确匹配 |
| 5 | `st.chat_input` 是 React 受控组件 | 用 `fill()` + `press("Enter")`，**不要** `type()` |
| 6 | 文件上传是真实 `<input type=file>` | `set_input_files` 直接喂 `[data-testid="stFileUploaderDropzoneInput"]` |
| 7 | **Streamlit 脚本异常不报 HTTP 错**，只在页面画红色 traceback | 断言页面无 `[data-testid="stException"]`（该 testid 已在 Streamlit 包内核实存在），否则"页面没崩"是假象 |
| 8 | 菜单切换后要等新页面 heading 出现 | 等 `[data-testid="stHeading"]` 文本变化 |
| 9 | 上传会触发 `txt_main()` 全量扫描 `documents/` | 用 `.txt` 小文件；测完清理 `documents/` 与 `txt/` 新产物 |
| 10 | **`st.session_state.history` 跨用例残留**（`rag_page.py:8`） | pytest-playwright 的 `page` fixture 是 function-scoped，每次新 context → 新 websocket → 新 session ✅。**但**：不要自定义 `page` fixture、不要把多个断言塞进一个用例，否则消息计数不是 2 |
| 11 | **Streamlit 冷启动要跑整个脚本** | E2E 首屏超时给到 60 秒，不要给 10 秒 |

---

## §7 运行方式

```bash
# 快回归（秒级，不碰浏览器/真 LLM）
pytest -m "not slow and not e2e" -v

# 浏览器 E2E（失败自动留 trace/video）
pytest -m e2e -v --tracing=retain-on-failure

# 真环境冒烟（花钱、慢）
pytest -m slow -v

# 全量
pytest -v
```

---

## §8 验收标准

| # | 标准 |
|---|---|
| A1 | `pytest -m "not slow and not e2e"` **全绿**。⏱️ **时间预算 < 60 秒**，不是 30 秒 —— 实测 `import main` 就要 **5.1 秒**、`import agent.runtime` **3.5 秒**（冷启动 .pyc 时 `import main` 更慢，实测过 12.5 秒）。§11 D-14 |
| A2 | `pytest -m e2e` 全绿（E4 报 `xfailed` 属正常） |
| A3 | F3 / F4 能**复现**"工具超时 / 工具失败时会发生什么"的确切行为（状态字段、ToolMessage 载荷、图是否终止、最终答案） |
| A4 | 公共不变式在 F1–F10 全部成立（悬空 tool_calls == 0） |
| A5 | 现有 13 个用例**不回归** |
| A6 | `pytest` 默认不再跑那 25 分钟的 `test_vector_split.py` |
| A7 | **F1c 成立** —— 工具 chunk 文本确实出现在 synth 的 prompt 里（grounding 不是空断言） |
| A8 | **在干净 clone 上按 §7 的命令能跑通**（当前仓库无 CI，这是"能进 CI"的前置条件） |

---

## §9 风险与已知局限

| # | 风险 | 应对 |
|---|---|---|
| R1 | 假 LLM 与真实 LLM 行为不同，可能掩盖真实 prompt 问题 | S1–S4 真实冒烟兜底；prompt 文本类断言明确排除在本设计外 |
| R2 | E2E 依赖 Streamlit 内部 `data-testid`，Streamlit 升级可能改 | 选择器集中在 conftest 的常量里，改一处即可 |
| R3 | 真 LLM 冒烟花钱且不稳定 | 标 `slow`，默认不跑；S3 已知 flaky（v2.2 实测 T06/T10 路由失败），失败时打印实际工具名供人工判断 |
| R4 | 上传测试污染 `documents/` 与 `txt/` | fixture 里记录并在测试后清理 |
| R5 | `test_vector_split.py` 标 slow 后没人跑 → 摄取链路腐烂 | 加一条**永远跑**的纯切分单测（不 embed、不连 Milvus），顺带钉住 P1-7（YAML 300 vs 代码 280 的漂移） |
| R6 | E2E 每次起 Streamlit，慢且吃内存 | E2E 标 marker，默认不跑；一个 session 只起一次 |
| R7 | 假后端的响应体与真实后端漂移 → E2E 假绿 | §3.5 把契约写死；假后端从**真实 api 模块**的 pydantic 模型取字段名，不手写 |
| R8 | **`reflect` 的"工具失败时不判 re_iterate"硬约束测不到** | 假 reflect 被剧本编排，永远返回剧本值 → 这条**只能**靠真 LLM（S4），且天然 flaky。本轮**明确不覆盖**，不假装覆盖 |

---

## §10 后续（不在本设计范围）

| 项 | 依据 |
|---|---|
| 重建评估集口径（`expected_tool` 从二值改 4 工具） | §8 P0-1 |
| 修 P1-1（`/rag` 前端字段名）→ E4 的 xfail 转正 | §8 P1-1 |
| CI workflow | 本设计先保证"本地一条命令能跑"（A8） |
| Agent 多轮记忆的测试 | 依赖 checkpointer 落地（P2-1） |
| LangSmith 观测（Tracing） | 本轮明确排除；后续单独做 |
| 修 `runtime._extract_answer` 的占位消息问题 | F9a / F11 会把它固化成 xfail，是修它的前置 |

---

## §11 自审修订记录（2026-11-16）

v1 设计做了一轮**代码级自审**（每条都核对到文件行号）。以下是发现的问题与修订。

### 11.1 致命（1 条）

| # | 问题 | 证据 | 修订 |
|---|---|---|---|
| **D-1** | **`page.route()` 拦截不到后端 → 整个 L4 浏览器层无法执行** | 三个页面的后端调用都是 **Streamlit 服务端进程**里的 `requests.post`：`rag_page.py:37-41`、`rag_direct_page.py:27-33`、`repo_admin.py:35-36`。`page.route()` 只拦**浏览器进程**发出的请求 | §3.4 改为"进程外假后端 + `API_BASE_URL` 注入"；连带 §5.1（改前端地址是前提）、§5.5（E2E 不复用用户 Streamlit）、§4.3（E7 改为"后端返 500"） |

### 11.2 必然失败的硬断言（3 条）

| # | 问题 | 证据 | 修订 |
|---|---|---|---|
| **D-2** | C4「空 query → 422」写反了 | `api/api_agent.py:18` → `query: str = Field(...)`，**无 `min_length`** → `{"query": ""}` 返回 200，只有**缺字段**才 422 | C4 改为"缺 `query` 字段 → 422"，并显式注明空串是 200 |
| **D-3** | F7/F8 的"被调次数"口径含混 | `reflect_node.py:86-91`：第 4 次进 reflect 撞上限**不调 LLM** → LLM 调用 3 次、节点进入 4 次；`iter_node.py:69-73`：第 3 次进 iter **不调 LLM** → LLM 调用 2 次、节点进入 3 次 | F7/F8 拆成"节点进入 N 次"+"LLM 调用 M 次"两个数字 |
| **D-4** | F9 把三种完全不同的超时时机压成一条 | (a) 进 iter 前过期 → `iter_node.py:51-56` 短路 → `should_continue` 走 `"__end__"` → **synth 从未执行** → `runtime._extract_answer` 倒着找到的是内部占位 `"已达总时限，停止思考"`，不是"回答超时…"。(b) synth 前过期 → `synth_node.py:47-54` 短路。(c) reflect 时过期 → `reflect_node.py:77-83` 强制 end | 拆成 **F9a / F9b / F9c** 三条，各自独立构造；F9a 用 `xfail(strict=True)` 固化当前占位行为 |

### 11.3 测了等于没测（8 条）

| # | 问题 | 修订 |
|---|---|---|
| **D-5** | **没有断言"工具结果真的流到了综合节点"** —— 假 synth 无论收到什么都返回固定答案，"答案非空"恒真 | 新增 **F1c**：断言 chunk 原文出现在假件记录的 synth prompt 里 |
| **D-6** | F1 的"ToolMessage 内容 == 原始 chunk"表述错 —— `rag_tool.py:64` 返回的是 `"\n\n---\n\n".join(chunks)` 拼接串 | F1 断言写成精确拼接串 |
| **D-7** | F1b 只断言"2 个独立 key"，没钉死"key == 调用 id"（D1 的核心约束） | F1b 改为 `set(tool_status.keys()) == {两个 tool_call id}` |
| **D-8** | `runtime._extract_answer`（`runtime.py:43-48`）倒着找最后一条 AIMessage，会拿到 `"READY"` / `"已达迭代上限，结束"` / `"已达总时限，停止思考"` —— **项目现状.md §2.8 明确说不可靠，但 runtime 正在这么做**，无人守护 | 新增 **F11**：断言 `ask()` 返回的答案不是任何内部占位；F9a 把它固化成 xfail |
| **D-9** | reflect prompt 的"工具 timeout/error/empty 时不判 re_iterate"硬约束**不可能**被假件覆盖（假 reflect 被剧本编排） | §1.3 明确列为非目标；新增 **S4**（真 LLM，flaky，只断言"不失控"）；§9 R8 显式承认本轮不覆盖 |
| **D-10** | E5 只断言"文本 `完成：` 出现" —— 假后端返 `uploaded_files: []` 也照样过 | E5 断言数量 **> 0** |
| **D-11** | **后端上传逻辑完全没测**，而它是最该测的：路径穿越（`api_file.py:49-64`）、类型白名单（:67-73）、同名跳过/覆盖（:75-86）—— 零外部依赖、零成本 | 新增 **C8 / C9 / C10** |
| **D-12** | F2 只断言 `status=empty`，漏了 v2.2 的关键契约：**工具返回空串而不是中文兜底串**（`rag_tool.py:52-54`） | F2 增加"ToolMessage 内容是空字符串"断言 |
| **D-13** | 兜底路由分支一个没测：`should_continue.py:51`（未知 action → END）、`:24-31`（非 AIMessage/乱码 → synth） | 新增 **F10** |

### 11.4 未声明的隔离 / flaky 风险（8 条）

| # | 问题 | 修订 |
|---|---|---|
| **D-14** | A1 的 "< 30 秒"不现实 —— 实测 `import main` **5.1 秒**（冷 .pyc 时 12.5 秒）、`import agent.runtime` **3.5 秒** | A1 改为 **< 60 秒** |
| **D-15** | patch `LLMmodel.create_minimax` 是全局的，而 `main.py:59-63` 在**模块级**调它 → 若 `main` 在 patch 之后 import，默认模型变假件 | §3.6 规则 1/2：`import main` 必须在模块顶层；L3 不得 patch |
| **D-16** | `switch_model` 改的是进程全局模型，C7 会污染后续用例 | §3.6 规则 3 + C7 标注 |
| **D-17** | `runtime._graph` 是模块级全局单例 —— 实现者可能误以为"图缓存了 patch 没用"而去改 `_get_graph` | §3.1 补充核实结论：`graph.py` 全文无 LLM 构造，patch 在 invoke 期生效，**不要**重建图 |
| **D-18** | E2E 无法复用用户已开的 Streamlit（env 注入丢失） | §3.4/§5.5 明确 E2E 每次自起 8511 |
| **D-19** | 假后端响应体形状未规定 → 误返 `{"answer":...}` 会让 E4 意外 XPASS（strict=True → 报失败）或让 E1 KeyError | §3.5 写成硬规则表 |
| **D-20** | 目标写"能进 CI"但 §1.3 又说"不建 CI"，且没有一条验收标准是"干净环境能跑" | A8 新增；§10 保留 CI 为后续 |
| **D-21** | `test_vector_split.py` 标 slow 后无人跑 → 摄取链路腐烂 | §9 R5：补一条**永远跑**的纯切分单测 |

### 11.5 其它精确性修正

| # | 问题 | 修订 |
|---|---|---|
| **D-22** | F9 无法用 `runtime.ask()` —— `runtime.py:95` 写死 `deadline = now + 90` | §3.6 规则 4 + §4.1 抬头：L2 用例直接 `graph.invoke()` |
| **D-23** | §5.1 的代码块让 `rag_page.py` 看起来"已有 API_BASE 变量" —— 实际**没有**，只有一处硬编码 `url=` | §5.1 单独给出 `rag_page.py` 的改法 |
| **D-24** | 未规定 TestClient 的 lifespan | §4.2 抬头：必须 `with TestClient(app) as client:` |
| **D-25** | 未声明 `session_state` 跨用例残留 | §6 坑 10 |
| **D-26** | F6 的断言 `next_action=rewrite` 与实测不符 | 实测终态是 `end`：兜底 action=rewrite 会再进 synth → 再进 reflect，第 4 次进 reflect 时 `reflection_count` 已达 `MAX_REFL` → 强制 end（`reflect_node.py:86-91`） | F6 改为断言 `last_critique` / `reflection_count=4` / 终态 `next_action="end"` / reflect LLM 3 次 |

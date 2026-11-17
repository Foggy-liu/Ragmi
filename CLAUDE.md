# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read First

Before doing anything else in this repo, read these in order:

1. `RULE.md` (repo root, local-only) — project constitution: collaboration rules (§A), background
   (§B), v1 → v2.2 evolution history (§C), and 24 engineering rules distilled from bugs already hit
   (§D). It supersedes any older memory file.
2. `docs/status/项目现状.md` — **the single source of truth for the current state**. §8 is a
   prioritized issue list (P0–P3) with file paths and line numbers; start work from there.
3. `docs/status/测试现状.md` — only when the task touches tests: what each script under `test/`
   actually measures and its measured result.
4. `docs/status/项目优化.md` — what each past change did and what it left behind.

Ground every statement in the code, not in prose: `docs/plan/`, `docs/note/`, `docs/archive/`, and
`test/archive/` describe earlier versions and are stale in places. Do not quote them as current fact.

After reading, state briefly what the project is and which `§8` P-item you are picking up, then
proceed. Keep `docs/status/项目现状.md` in sync with the code whenever `agent/` behavior changes.

## Project Overview

RAGMI is a Python 3.11+ personal knowledge-base Q&A application. It combines a Streamlit frontend, FastAPI backend, LangGraph Agent, direct chat/RAG endpoints, document ingestion, Ollama embeddings, and Milvus vector search.

The repository exposes three distinct conversation paths:

- `/agent/chat`: LangGraph Agent that decides whether to call the RAG tool, then reflects on the answer.
- `/rag`: direct RAG pipeline with its own conversation history.
- `/chat`: direct LLM conversation with its own conversation history.

Do not describe `/agent/chat` as the only chat entry point. The frontend defaults to it, but the direct `/rag` and `/chat` APIs remain mounted.

## Commands

### Setup and services

```bash
pip install -r requirements.txt
cp .env.example .env

# Start Milvus
# The milvus service lives in docker-compose.yml — there is no separate docker-compose-milvus.yml.
# Milvus may need about 90 seconds before it is healthy.
docker-compose up -d milvus
curl http://localhost:9091/healthz

# Parse and vectorize documents into a fresh Milvus collection, then atomically move the configured alias.
python utils/txt_spliter/vector_main.py

# Start FastAPI backend (127.0.0.1:8000)
python main.py

# Start Streamlit frontend (port 8501)
streamlit run main_web.py

# Backend health/model-manager inspection
curl http://localhost:8000/debug/simple
```

`vector_main.py` reads parsed files from `txt/`. Upload processing places originals in `documents/` and parsing output in `txt/`.

### Tests and evaluation

```bash
# Fast regression (seconds; no browser, no real LLM)
pytest -m "not slow and not e2e" -v

# Browser E2E (keeps trace/video on failure)
pytest -m e2e -v --tracing=retain-on-failure

# Real-environment smoke (slow, costs money)
pytest -m slow -v

# Everything
pytest -v

# One test file / one test function
pytest test/test_agent_flow.py -v
pytest test/test_agent_flow.py::test_name -v
```

`test/archive/` holds the archived v2.1 evaluation scripts (`scripts/run_agent_eval.py` etc.) and the
historical score snapshots (`data/*.json`). `pytest.ini` sets `norecursedirs = archive probes` so
they are never collected. Their actual run status was measured on 2026-11-15: `run_agent_eval.py`
**does** still run in real-LLM mode (it needs `PYTHONPATH` pointed at the repo root, because
`Path(__file__).parent.parent` now resolves to `test/archive/` instead of the repo root) — only
its `--mock` branch is broken. `run_v1_baseline.py` runs but **overwrites
`data/v1_baseline_results.json` with 0/12 when the backend is down**. `retry_failed_cases.py`
merely re-prints cached numbers. See `test/archive/README.md`.

Currently live test files:

- `test/test_agent_timeout.py` — timeout/exception mechanism (11 cases, no Milvus or LLM needed).
- `test/test_main_routes_covered.py` — AST scan of `api/*.py` + `main.py`, prevents unmounted router dead code (2 cases).
- `test/test_agent_flow.py` — **L2 Agent flow layer**: runs the real LangGraph graph with a fake LLM (scripted) and a fake retriever. Covers tool success/empty/timeout/error, retrieval-failure ≠ retrieval-empty, LLM crashes, both loop guards, the three timeout timings, and the `ask()` contract (17 cases + a parametrized "no dangling tool_calls" invariant → 26 collected items).
- `test/test_api_contract.py` — **L3 API contract layer**: `TestClient` + `dependency_overrides`. Field shapes, missing-field 422, model switching, the upload validation logic (path traversal / type whitelist / same-name skip-or-overwrite), and the `RagModel` app-level singleton (12 cases).
- `test/test_tools.py` — **L2 tool layer**: pure-function checks on the tool bodies. Covers `calculator`'s AST-whitelist evaluation (arithmetic, unsafe-input rejection, malformed input) — the regression net for the `eval()` RCE fix — plus `rag_search`'s exception normalization (26 cases, always run).
- `test/test_rag_model.py` — **L2 retrieval layer**: the `core/rags/rags.py` failure semantics — "retrieval failed" raises `RetrievalError`, "retrieval empty" returns `[]`, and `/rag` stays resilient (7 cases, always run).
- `test/test_splitter.py` — pure-function splitter checks (6 cases, always run).
- `test/test_vector_split.py` — end-to-end `vector_split()`; requires a healthy Milvus and Ollama, and re-embeds every document, so it is slow (measured: 25 min 29 s for 1667 chunks). Marked `@pytest.mark.slow` — excluded from the default fast run.
- `test/test_eval_smoke.py` — real MiniMax + real Milvus smoke (**marked `slow`**).
- `test/e2e/test_browser_e2e.py` — Playwright against a **process-external fake backend** + a dedicated Streamlit on port 8511 (**marked `e2e`**).
- `test/e2e/real_stack_check.py` — **real-stack health check**, deliberately named so pytest never collects it (not `test_*.py`). Runs against the real backend (8000) + real Milvus/Ollama/MiniMax in a **visible Chrome**, sweeps all 9 endpoints (including negative paths: 422, path traversal, `.exe` whitelist, same-name skip, `switch_model` failure + restore) plus the 3 Streamlit pages, and writes screenshots + an HTML report to `test/e2e/_artifacts/` (gitignored). Costs money and needs every real service up. Run: `PYTHONIOENCODING=utf-8 python test/e2e/real_stack_check.py`. Measured 2026-11-17: 19/19 passed in 74 s.

The four-layer system is documented in `docs/status/测试体系.md`; its design is
`docs/plan/2026-11-16-test-suite-design.md`. As of 2026-11-17 the fast run is
**90 passed / 0 xfailed** and the browser layer is **8 passed** — the three
`xfail(strict=True)` markers that used to pin known defects (F9a_x / S5 / E4) are gone,
because P1-1, P1-2 and P1-7 are fixed.

**Coverage gap to keep in mind**: the fast suite now *does* run `graph.invoke()` — the Agent's
non-timeout routing branches, counter-reset semantics, and reflect decisions have 17 pytest
cases in `test/test_agent_flow.py`, plus a parametrized regression net asserting
"dangling `tool_calls` == 0". What is **not** covered: the reflect prompt's hard constraint
("never answer `re_iterate` after a tool timeout/error") — a scripted fake reflect cannot exercise
it, and the only real-LLM probe (S4) is inherently flaky. See `docs/status/测试体系.md` §6.

`test/probes/` holds manual verification scripts (`probe_*.py`). They are not pytest cases — the
filename pattern does not match `python_files = test_*.py`, so pytest never collects them. Run them
directly from the repo root. They document the `tool_calls` dangling / `tool_status` overwrite
findings; see `test/probes/README.md`. Both findings are now covered by pytest cases
(`test/test_agent_flow.py` F1b + the parametrized "no dangling tool_calls" invariant).

`test/README.md` is the per-file index: what each script tests, its measured result, and what
the suite does *not* cover. Read it before adding or running anything under `test/`.

There is no configured lint or build command. `pytest.ini` discovers `test/test_*.py`; not every script under `test/` is a pytest test.

## Runtime Architecture

### Frontend and API layer

`main_web.py` provides three Streamlit pages:

1. Agent smart Q&A, backed by `/agent/chat`.
2. Direct knowledge-base Q&A, backed by `/rag`.
3. Repository administration for document upload.

`main.py` creates the FastAPI application and mounts:

- `/chat` from `api/api_chat.py`
- `/rag` from `api/api_rag.py`
- `/agent/chat` from `api/api_agent.py`
- `/api/*` from the sub-application in `api/api_file.py`
- model-management routes from `api/api_model.py`

The application lifespan checks that `documents/` exists and probes Milvus without blocking startup on failure. Development CORS currently permits every origin; preserve the comment that production deployment should use a whitelist.

### Conversation paths

The direct paths use the application-level `ModelManager` initialized in `main.py` and obtained through FastAPI dependencies:

- `core/chat/chat.py` performs direct model conversation.
- `core/rags/rags.py:RagModel.chat()` retrieves chunks, builds a grounded prompt, invokes the selected model, and stores history through the global `MessageManager`.

FastAPI's `Depends` cache is **per request only** — it never spans requests. So a cheap
dependency (`get_chat_model`) may be built per request, but `get_rag_model` is an **app-level
singleton** on `app.state.rag_model`: `RagModel.__init__` costs ~0.45 s (measured 2026-11-17 —
**~0.42 s of it is building the embedding HTTP client**, i.e. two httpx clients each building
an SSL context; plus YAML reads and two health-check RPCs), while the actual retrieval only
takes ~0.10 s. A failed connection is **not cached**, so the next request retries.
See `api/dependencies.py`.

Note: this is **not** "a new Milvus gRPC connection per request" — pymilvus 2.6 has its own
`ConnectionManager` that caches the underlying gRPC channel per address (a second client
costs 0.000 s). The repeated cost is the embedding client plus config/health-check overhead.

The Agent path is intentionally decoupled from `app.state.model_manager`:

- `api/api_agent.py` calls `agent.runtime.ask()`.
- `agent.runtime` lazily compiles and reuses the LangGraph graph.
- Both the Agent node and reflection node explicitly create `MiniMax-M3.1-Flash` rather than using the YAML default model.
- `session_id` is passed as a LangGraph `thread_id`, but the graph has no checkpointer. Agent multi-turn persistence is therefore not implemented.

## LangGraph Agent (v2.2)

The Agent is a single-Agent, multi-tool ReAct-style graph with an LLM-as-judge reflection step. v2.2 replaced v2.1 to fix three bugs: the dual-role node, mixed-up counters, and the tool-timeout deadlock.

```text
START → iter
          ├─ tool_calls present → tools → iter (loop)
          └─ no tool call (incl. "READY" / 乱码 / iter_count ≥ MAX_ITER) → synth

synth → reflect

reflect
  ├─ end → END
  ├─ rewrite → synth（iter_count 已重置）
  ├─ re_iterate → iter（iter_count 已重置）
  └─ reflection_count ≥ MAX_REFL → 强制 end（兜底防死循环）

两条条件边在 expired=True 时都直接走 "__end__"（见「超时机制」）。
```

### 4 节点 vs v2.1 3 节点

v2.1 节点：`agent`（决策+综合双角色）/ `tools` / `reflect`

v2.2 节点：`iter`（纯决策，不写答案）/ `tools` / `synth`（综合）/ `reflect`

分离原因：v2.1 agent_node 同时承担"决定要不要调工具"和"写最终答案"两种 LLM 模式，互相干扰。v2.2 拆为 2 个节点 + `iter` 用 `READY` 信号交接。

### 2 counter vs v2.1 单 counter

v2.1：`iterations`（单计数器，混叠 agent_node 决策+综合次数，导致反思触发条件短路）

v2.2：两个独立计数器，各管自己的节点（`synth_count` / `MAX_SYNTH` 已删除 —— 职责转移给 reflect 节点后它成了不可达的僵尸参数）：

- `iter_count` — iter 节点调用次数，上限 `MAX_ITER=3`，reflect rewrite/re_iterate 时重置
- `reflection_count` — reflect 节点调用次数，上限 `MAX_REFL=3`，**永不重置**（绝对上限，防死循环）

**注意**：`MAX_REFL` 不是工具循环的刹车 —— 工具循环（`iter → tools → iter`）根本不经过 reflect 节点。
工具循环唯一的刹车是 `MAX_ITER`。改路由时两个都要保留。

### 工具状态

用 LangGraph 官方钩子 `ToolNode(ALL_TOOLS, wrap_tool_call=status_wrapper)` 拦截每次工具调用，
写 `state["tool_status"]` 字典。

**key 是调用 id，不是工具名。**调用 id 由模型生成、每次调用唯一。同一轮里 MiniMax 常常
并发调同一个工具 2~3 次（实测一次决策就发 2 个 `rag_search`），按工具名做 key 会让后一次
调用覆盖前一次的状态（实测：成功的那条被 timeout 冲掉）。

**value 是结构化条目** `{tool, status, code, retryable}`：

| status | code | retryable | 触发条件 |
|---|---|---|---|
| `success` | `OK` | — | 工具返回非空内容 |
| `empty` | `EMPTY_RESULT` | — | 工具返回空字符串 |
| `timeout` | `TOOL_TIMEOUT` | ✅ | 工具抛 `AgentTimeoutError` |
| `error` | `TOOL_ERROR` | ❌ | 工具抛 `AgentToolError` 或其他异常 |

`retryable` = "这个失败重试有没有意义"。当前只有 timeout 为 True；更细的分类
（限流/服务不可用 → 可重试，参数错/代码 bug → 不可重试）暂时做不了，因为
`core/rags/rags.py` 的 `retrieve()` 用 `except Exception: return []` 把异常吞了。

不要重新继承 `ToolNode` 并重写 `__call__`：`ToolNode.__init__` 把被调用的方法钉死成 `_func`，
LangGraph 走 `node.invoke(...)` → `self.func`，子类重写的 `__call__` 永远不会被执行。
`wrap_tool_call` 是框架提供的官方拦截点，不碰内部实现。

失败时仍必须写 `ToolMessage`，否则 graph 卡在"有 tool_calls 但没应答"，后续 LLM 调用会被判非法。
失败时 ToolMessage 的内容是**结构化 JSON 载荷**（不是中文散文）：

```json
{"code": "TOOL_TIMEOUT", "status": "timeout", "retryable": true, "message": "调用超时：..."}
```

成功时内容保持原样（原始检索片段），不做包装。

reflect prompt 硬约束：工具 timeout/error/empty 时不应判 `re_iterate`（否则 `iter → tools(超时) → iter` 死循环）。
注意这条硬约束与载荷里的 `retryable: true` 语义不同 —— `retryable` 描述的是"这类错误重试有意义"，
硬约束描述的是"本 Agent 不靠 re_iterate 重试"（防死循环优先）。

### 超时机制

三层，职责不重叠：

```text
第 1 层  异常归一化   agent/errors.py
         AgentError / AgentTimeoutError（可重试） / AgentToolError（不可重试）
         工具层把第三方异常翻译成自家异常，只翻译一次

第 2 层  单次动作超时 agent/timeout.py :: Timer
         Timer(TOOL_TIMEOUT).call(fn, ...) —— 超时抛 AgentTimeoutError

第 3 层  整图总时限   state["deadline"] + agent/timeout.py :: is_expired()
         runtime.ask() 写入 deadline = time.time() + TOTAL_TIMEOUT
         每个节点动手前协作式检查，超时就地收手
```

配置在 `configs/agent_config.yaml` 的 `agent.timeout` 段（`llm` / `tool` / `total`），
由 `agent/constants.py` 加载导出并 assert 校验。改超时只改 YAML。

两条硬规则：

- **`.with_config({"timeout": N})` 是死代码** —— `langchain_core` 从不读 `RunnableConfig["timeout"]`。
  超时只能在构造时传：`LLMmodel.create_minimax("MiniMax-M3.1-Flash", timeout=LLM_TIMEOUT)`。
  三个 LLM 节点都走这条路径。
- **Python 杀不掉线程**（没有 `Thread.terminate()`）。超时只能"不再等"，
  底层线程仍会跑完并占着连接。所以工具层自身也要有界。

`api/api_agent.py` 的端点必须是**普通 `def`**，不能是 `async def` ——
`ask()` 是同步阻塞的，写在 `async def` 里会占住事件循环，把整个 FastAPI 服务卡死。
FastAPI 对普通 `def` 端点会自动丢到线程池。

### 配置

`configs/agent_config.yaml` 定义 `MAX_ITER` / `MAX_REFL` / `timeout.{llm,tool,total}`。
`agent/constants.py` 加载并导出，启动时 assert 校验。

### 工具清单

4 个：`rag_search`（已有）/ `calculator` / `weather` / `web_search`（3 个占位实现）。

### 节点细节

- `agent/nodes/iter_node.py`：`bind_tools(ALL_TOOLS)`，prompt 强制"不调工具时输出 READY"，含 try/except + `iter_count + 1 >= MAX_ITER` 边界检查 + `is_expired` 检查。边界检查必须用 `iter_count + 1`（`iter_count` 是"已跑过几次"，本次调用之后才达到上限）；写成 `iter_count >= MAX_ITER` 会白调一次 LLM，而它发出的 tool_calls 会被 `should_continue` 丢弃 → 悬空消息
- `agent/nodes/synth_node.py`：不挂 `bind_tools`，按 `state["last_critique"]` 是否空切换 prompt 模式（首次 vs 重写），含 try/except + `is_expired` 检查（放在 `_get_llm()` 之前，避免白加载一次 LLM）
- `agent/nodes/reflect_node.py`：用 `with_structured_output(ReflectOutput)`，Pydantic 解析；失败 fallback `next_action=rewrite`；超 `MAX_REFL` 强制 end；rewrite/re_iterate 时重置 iter_count
- `agent/nodes/status_tool_wrapper.py`：官方 `wrap_tool_call` 钩子，4 种 status 值 + 结构化 ToolMessage 载荷 + `format_tool_status()` 渲染函数（iter/synth/reflect 三个节点共用）
- `agent/nodes/material.py`：`collect_round_material(messages)` —— 取"最后一条 HumanMessage 之后的全部 ToolMessage"（三个节点统一用它取素材）
- `agent/nodes/should_continue.py`：含 2 个条件边函数（`should_continue` + `after_reflect`），两者都检查 `expired`

### 状态 Schema

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    iter_count: Annotated[int, _inc_iter]
    reflection_count: Annotated[int, _inc_refl]
    tool_status: Annotated[dict, _merge_tool_status]   # key=调用 id, value={tool,status,code,retryable}
    last_critique: str
    next_action: str      # reflect 的决策：end / rewrite / re_iterate
    deadline: float       # 图级总时限（绝对时间戳）
    expired: bool         # 已超时标志 → 条件边直接 END
    last_answer: str      # synth 最近一次写出的答案（超时兜底时交出去）
```

字段必须显式声明，否则 LangGraph 不会把它写进 state（`next_action` 曾经因此恒为缺省值）。
`last_answer` 不能靠"倒着找最后一条 AIMessage"推导 —— messages 里混着 iter 的占位消息（`"READY"`），
会把占位消息当成答案交出去。

### Runtime

`agent.runtime.ask()` debug 模式返回 5 字段：`answer` / `iter_count` / `reflection_count` / `tool_called` / `last_action`。`api/api_agent.py` 仍调 `ask()` 非 debug 模式。

`runtime.py` 显式给 LangGraph `recursion_limit`（从 `MAX_ITER` / `MAX_REFL` 推导，不写死），
否则最坏情况 28 步会撞默认上限 25，抛 `GraphRecursionError`。

### 错误和调试

`ask()` 仍捕获 graph 调用异常返回友好消息（不抛 HTTP 500）。`ask()` debug=True 返回 dict 含 `last_action` 字段（end / rewrite / re_iterate / error）。

### 已知遗留

- **Agent 没有多轮记忆**：`runtime.ask()` 每次 invoke 都传全新的
  `{"messages": [HumanMessage(question)]}`；`session_id` → `thread_id` 传了但图没有
  checkpointer，`thread_id` 没人读。三个 LLM 节点也从不把 `state["messages"]` 发给 LLM
  （每次从零拼 prompt：原问题 + 工具素材 + 计数器）。做记忆前要先处理 iter 的占位消息
  （`"READY"` / `"已达迭代上限，结束"`）—— 它们会一起进历史。
- **`retryable` 还不能细分**：工具层目前只拿到 `AgentToolError` 这一个"其他错误"的桶，
  区分不出限流/服务不可用（可重试）与参数错/代码 bug（不可重试）。前置已具备
  （`RetrievalError` 保留 `__cause__`），还需要 `RetrievalError` 带更细的错误码。

> 已修复（2026-11-17）：`empty` 状态不精确 —— `core/rags/rags.py` 现在抛 `RetrievalError`
> 表示"检索失败"，`[]` 只表示"检索为空"；`rag_tool.py` 把它翻译成
> `AgentToolError` / `AgentTimeoutError`。
> 详见 `docs/status/项目现状.md` P2-7。
>
> 已修复（2026-11-17）：Ollama 调用不限时 —— `EmbeddingModel._init_client` 把
> `PLATFORMS.ollama.timeout`（60 s）透传给 `OllamaEmbeddings(client_kwargs={"timeout": ...})`
> → `ollama.Client` → httpx。工具外层的 `Timer` 仍是"不再等"，底层连接现在自己也有上限。

> 已修复（2026-11-15，O-006）：`tool_calls` 悬空 —— `iter_node` 的边界检查改成
> `iter_count + 1 >= MAX_ITER`，最后一轮不再调 LLM，从根上不产生悬空消息。
> 实测悬空数从 2/7 降到 0/5。详见 `docs/status/项目优化.md` O-006。

## RAG and Vector Storage

`core/rags/rags.py` owns the reusable retrieval pipeline:

1. Create the configured embedding/Milvus settings through `EmbeddingModel`.
2. Reuse `EmbeddingModel.embedding` (the `langchain_ollama.OllamaEmbeddings` client) to embed
   queries — **do not construct a second one**; the model name and base URL come from the
   config, and the client carries a 60 s timeout.
3. Search the configured Milvus collection/alias for the top five chunks.
4. Either return chunks through `retrieve()` or build a grounded prompt and generate through `chat()`.

**The embedding model name has one source of truth**: `EmbeddingModel._resolve_model_name()`
(`EMBEDDING_MODEL` env var > YAML `DEFAULT_EMBEDDING_MODEL.model_name`). The indexing side
reads the same value through `utils/txt_spliter/vector_main.py::resolve_embed_settings()`.
A mismatch between the two sides does **not** raise — `bge-large` and `bge-m3` are both
1024-dimensional — it just makes every retrieval return noise.

`utils/txt_spliter/vector_main.py` rebuilds vector data safely:

1. Parse all files available through the splitter.
2. Generate embeddings by calling Ollama `/api/embed` directly in batches.
3. Create a timestamped collection such as `<alias>_<timestamp>`.
4. Insert chunks and build an `AUTOINDEX` cosine index.
5. Atomically create or move the stable alias from `configs/model_config.yaml`.
6. Leave the old collection intact for manual cleanup or rollback.

Do not replace the direct Ollama HTTP embedding path in `vector_main.py` with `langchain_ollama` without investigating its documented local proxy/port issue. Note that query-time retrieval in `core/rags/rags.py` still uses `langchain_ollama`, so indexing and querying use different *clients* for the same embedding *model* — but they must agree on the model name.

## Configuration

`configs/model_config.yaml` defines Ollama, Alibaba Cloud, OpenAI-compatible, and MiniMax platforms plus Milvus/text-splitting settings. Environment placeholders are resolved from `.env`; important variables include:

- `MINIMAX_BASE_URL`, `MINIMAX_API_KEY`
- `ALIYUN_BASE_URL`, `ALIYUN_API_KEY`
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`
- `MILVUS_HOST`, `MILVUS_PORT`
- optionally `OLLAMA_BASE_URL`, `EMBEDDING_MODEL`

Model selection: direct chat/RAG use the managed current model, while Agent nodes explicitly select MiniMax-M3.1-Flash. These currently name the same model, but the Agent path obtains it independently of `app.state.model_manager` — switching the YAML default does not change which model the Agent calls.

## Important Constraints

- Keep Agent tool output as raw retrieved chunks; final synthesis belongs to the Agent LLM.
- Make Agent routing changes in the graph, prompts, tool schema, or conditional edges—not by reintroducing the removed custom JSON/confidence router.
- Preserve both loop guards when modifying graph routing.
- Key `state["tool_status"]` by tool-call id, never by tool name — one round can call the same tool several times concurrently, and a name key silently overwrites earlier results.
- Keep `iter_node`'s limit check as `iter_count + 1 >= MAX_ITER`. `iter_count` is the count of *previous* visits, so `iter_count >= MAX_ITER` fires one round late, wasting an LLM call whose `tool_calls` are then dropped (leaving a dangling AIMessage that MiniMax rejects with HTTP 400).
- Always answer a tool call with a `ToolMessage` — a call without one leaves the graph in an invalid message state.
- Never use `.with_config({"timeout": N})` — it is dead code. Pass `timeout=` when constructing the client.
- Keep `api/api_agent.py`'s endpoint as a plain `def`. `ask()` is blocking; `async def` would stall the whole FastAPI event loop.
- Normalize tool-layer exceptions to `AgentTimeoutError` / `AgentToolError` exactly once, in the tool itself. Downstream layers should not re-translate third-party exception types.
- **Retrieval failure is not retrieval emptiness.** `core/rags/rags.py` raises `RetrievalError` when the store is down or the query fails, and returns `[]` only when there is genuinely nothing to return. `agent/tools/rag_tool.py` translates it (`__cause__` is a timeout → `AgentTimeoutError`, else `AgentToolError`). Never collapse the two back into `[]` — that is what makes `tool_status` useless.
- The embedding model name comes from `EmbeddingModel._resolve_model_name()` only (`EMBEDDING_MODEL` env var > YAML). Never hardcode `bge-large` — a silent mismatch with the indexing side returns noise, not an error.
- Do not build a second `OllamaEmbeddings` in `core/rags/rags.py`; reuse `EmbeddingModel.embedding` so the timeout and the model name stay in one place.
- Always construct `MilvusClient` with `uri=f"http://{host}:{port}"`. pymilvus 2.6 has no `host`/`port` parameters — those keys fall into `**kwargs` and are **silently ignored**, so the client connects to the default `http://localhost:19530`. That happens to work on the host and always fails inside a container.
- `requirements.txt` is a **fully pinned lock file** (139 packages, closure resolved with linux markers). Pinning only direct dependencies lets transitive deps drift to newer versions and break the container at import time. To change a dependency: edit the "直接依赖" section, then re-resolve the closure — do not hand-edit the locked section.
- `get_rag_model` (`api/dependencies.py`) is an **app-level singleton** on `app.state.rag_model`. FastAPI's `Depends` cache does not span requests, so building a `RagModel` per request costs a new Milvus gRPC connection every time.
- Treat Agent `session_id` as non-persistent until a LangGraph checkpointer is added.
- `api/api_file.py` is mounted under `/api`, so its effective upload endpoints are `/api/upload-and-parse` and `/api/batch-upload-and-parse`.
- When adding or removing API modules, update or satisfy `test/test_main_routes_covered.py`; it exists to prevent unmounted `api_*.py` dead code.
- When changing `agent/` behavior, add or update a case in `test/test_agent_flow.py` (graph / flow) or `test/test_agent_timeout.py` (timeout / exception mechanism); when changing a tool's body, add or update a case in `test/test_tools.py`. The archived scripts under `test/archive/` no longer run.
- The Agent's internal placeholder messages are defined once in `agent/constants.py` (`SIGNAL_READY` / `SIGNAL_MAX_ITER` / `SIGNAL_EXPIRED`, grouped as `INTERNAL_SIGNALS`). Producers and consumers must reference the constants, never the string literals — a copied literal drifts and turns the "the answer is not a placeholder" assertion into a tautology.
- `calculator` must never use `eval()`. It evaluates a hand-rolled AST whitelist (`agent/tools/calculator_tool.py`); keep `test/test_tools.py` green if you touch it.
- The frontend reads `API_BASE_URL` (default `http://localhost:8000`) — all three `web_page/*.py` files. Do not hardcode a backend address again; the previous mix of `localhost:8000` and `api:8000` broke container deployments.

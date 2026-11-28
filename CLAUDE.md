# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read First

Before doing anything else in this repo, read these in order:

1. `RULE.md` (repo root, local-only) — project constitution: collaboration rules (§A), background
   (§B), v1 → v2.2 evolution history (§C), and 24 engineering rules distilled from bugs already hit
   (§D). It supersedes any older memory file.
2. `docs/status/项目现状.md` — **the single source of truth for the current state**. §8 is a
   prioritized issue list (P0–P3) with file paths and line numbers; start work from there.
3. `docs/status/项目全景图.md` — how the code is wired together: a 30-minute reading order, the
   two data flows (offline ingest / online query), the Agent graph in detail, the **15**
   invariants that must not break (§5), and a risk map (§6).
4. `docs/status/测试现状.md` — only when the task touches tests: what each script under `test/`
   actually measures and its measured result.
5. `docs/status/项目优化.md` — what each past change did and what it left behind (this is where
   the full incident narrative lives; CLAUDE.md keeps only the rule that came out of it).
6. `docs/status/项目能力与边界.md` — only when asked "how good is this project / what can it
   do": measured limits, an explicit list of what it cannot do, and what is missing for
   productization.
7. `docs/status/项目速览.md` + `docs/status/术语表.md` — **human onboarding** (not needed by
   Claude): the速览 expands 42 framework/project concepts with `file:line`, and the术语表 is a
   54-entry lookup table. Read these when a human asks "how do I understand this project" or
   "what does this term mean".

Only `docs/plan/` and `docs/status/` are tracked by git. `docs/task/`, `docs/personal/`, `docs/note/`
and `docs/archive/` are local-only. `docs/plan/` describes earlier versions and is stale in places —
ground every statement in the code, not in prose.

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
# ⚠️ 必须用 `python -m`（或 PYTHONPATH=.）：直接跑脚本时 sys.path[0] 是 utils/txt_spliter/，
#    `import utils` 会 ModuleNotFoundError。
python -m utils.txt_spliter.vector_main

# Start FastAPI backend (127.0.0.1:8000)
python main.py

# Start Streamlit frontend (port 8501)
streamlit run main_web.py

# Backend health/model-manager inspection
curl http://localhost:8000/debug/simple
```

`vector_main.py` reads parsed files from `txt/`. Upload processing places originals in `documents/` and parsing output in `txt/`.

### Pytest commands

```bash
# Fast regression (no browser, no real LLM)
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

There is no configured lint or build command. `pytest.ini` discovers `test/test_*.py`; not every script under `test/` is a pytest test.

## Tests and evaluation

### Two live offline evaluations (neither is a pytest case)

Both are **non-pytest** (`pytest.ini` sets `norecursedirs = archive probes eval .* build dist node_modules venv __pycache__`;
`eval_quality/` is not collected because no file matches `python_files = test_*.py`). Both need a real
MiniMax key and **cost money**. Run both from the repo root.

**① `test/eval/` — tool routing** (`run_agent_eval.py`, 12 cases → routing accuracy + stability)

```bash
PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py            # real LLM
PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py --mock     # reflect uses a fake LLM
```

Latest snapshot `data/agent_eval_results.json`: **75.0% = 9/12** (2026-11-18, 二值口径), stability
12/12, 21 tool calls all `success`. Later runs on the *same* code: 83.3% (10/12, 2026-11-15) and
**91.7% = 11/12** (2026-11-26, 具体工具名口径, double-reported alongside the binary rubric). The
spread is **LLM sampling, not code drift** — so quote the range 75%–92% and always say "single
sample". Stable错例 across runs: **T06** only.

**② `test/eval_quality/` — answer quality + reflection ablation** (2026-11-27, see the dedicated
section below)

```bash
PYTHONIOENCODING=utf-8 python test/eval_quality/judge_answer_quality.py --selftest   # judge gate
PYTHONIOENCODING=utf-8 python test/eval_quality/run_answer_quality_eval.py --recall-check
PYTHONIOENCODING=utf-8 python test/eval_quality/run_answer_quality_eval.py --repeat 3
PYTHONIOENCODING=utf-8 python test/eval_quality/reflect_ablation_eval.py --repeat 3
PYTHONIOENCODING=utf-8 python test/eval_quality/reflect_ablation_eval.py --repeat 3 --improve
```

### Currently live pytest files

| File | Layer | What it measures |
|---|---|---|
| `test/test_agent_timeout.py` | L1 | timeout/exception mechanism (11 cases, no Milvus or LLM needed) |
| `test/test_main_routes_covered.py` | L1 | AST scan of `api/*.py` + `main.py` — prevents unmounted router dead code (2 cases) |
| `test/test_agent_flow.py` | L2 | **runs the real LangGraph graph** with a scripted fake LLM + fake retriever: tool success/empty/timeout/error, retrieval-failure ≠ retrieval-empty, LLM crashes, both loop guards, the three timeout timings, the `ask()` contract (17 cases + a parametrized "no dangling tool_calls" invariant → 26 collected items) |
| `test/test_tools.py` | L2 | tool bodies: `calculator`'s AST-whitelist evaluation (the `eval()` RCE regression net) + `rag_search`'s exception normalization (26 cases) |
| `test/test_rag_model.py` | L2 | `core/rags/rags.py` failure semantics — "retrieval failed" raises `RetrievalError`, "retrieval empty" returns `[]`, `/rag` stays resilient (7 cases) |
| `test/test_splitter.py` | L2 | pure-function splitter checks (6 cases) |
| `test/test_file_filter.py` | L2 | `utils/docs/manager/filter.py` MD5 content-hash dedup: same-content skip, different-filename-same-content skip, **re-upload with a newer source mtime still skips** (the old mtime gate defeated dedup on the upload path), changed content re-processes, **the index stores filenames only** (host and container share one index), legacy absolute-path indexes still resolve, and "upload the same document twice produces exactly one output file, no `_1` copy" (9 cases) |
| `test/test_api_contract.py` | L3 | `TestClient` + `dependency_overrides`: field shapes, missing-field 422, model switching, upload validation (path traversal / type whitelist / same-name skip-or-overwrite), the `RagModel` app-level singleton (12 cases) |
| `test/test_eval_smoke.py` | L4 | real MiniMax + real Milvus smoke (**marked `slow`**) |
| `test/test_vector_split.py` | L4 | end-to-end `vector_split()`; needs healthy Milvus + Ollama and re-embeds everything (**marked `slow`**) |
| `test/e2e/test_browser_e2e.py` | L4 | Playwright against a **process-external fake backend** + a dedicated Streamlit on port 8511 (**marked `e2e`**) |
| `test/e2e/real_stack_check.py` | — | **real-stack health check**, deliberately named so pytest never collects it (not `test_*.py`). Sweeps all 9 endpoints (including negative paths: 422, path traversal, `.exe` whitelist, same-name skip, `switch_model` failure + restore) plus the 3 Streamlit pages in a **visible Chrome**; writes screenshots + an HTML report to `test/e2e/_artifacts/` (gitignored). Run: `PYTHONIOENCODING=utf-8 python test/e2e/real_stack_check.py`. Measured 19/19 passed in 74 s (2026-11-17) and 64 s (2026-11-18) |

`test/archive/` and `test/probes/` hold the outdated v1/v2.1 scaffolding and one-off probe scripts.
Both were superseded by pytest cases and **both are gitignored — never pushed**, so a fresh clone
will not see them. If you need their history, read the local copies or `git log -- test/archive/`.
**Do not reference `test/probes/` in code or in pushed docs.**

### Measured suite state

- **Fast run: 99 passed / 13 deselected / 0 xfailed** (2026-11-27; same 99 on 2026-11-25). The three
  `xfail(strict=True)` markers that used to pin known defects (F9a_x / S5 / E4) are gone — P1-1,
  P1-2 and P1-7 are fixed; the +9 are `test/test_file_filter.py`.
- **Browser layer: 8 passed** only when the real backend is up on :8000. With it down,
  `test_e8_real_backend_smoke` is **skipped** (needs a live backend) and the layer reports
  **7 passed / 1 skipped** (measured 2026-11-22). That skip is an environment condition, not a failure.
- **Coverage** (measured 2026-11-22, `pytest -m "not slow and not e2e" --cov=.`): `agent/` **91%**,
  whole project **56%**. The low end is ingestion (`utils/docs/` 11–20%) and the Streamlit pages
  (`web_page/` 0% — only exercised by the browser E2E, never by pytest). There is **no threshold
  assertion and no CI**, so coverage can silently regress.
- **The fast suite is not hermetic — its runtime depends on Milvus being reachable** (re-measured
  2026-11-25): **99 passed in 108.70 s with Milvus down** vs **7.5–8.9 s with Milvus up** (six
  consecutive runs: 8.89 / 7.49 / 7.60 / 7.89 / 7.83 / 7.72 s). The cost is not in the tests but in
  `test/test_api_contract.py`'s 12 setups, each ~10–11 s: `main.py`'s lifespan probes Milvus on
  every startup (`MilvusClient.list_collections()`), an unreachable Milvus blocks that probe
  ~10–11 s, and `TestClient` re-triggers the lifespan per test. With Milvus up, those 12 lifespans
  cost ~6.7 s total (~0.55 s each — `OllamaEmbeddings()` construction is 0.46 s of that) and the
  other 87 cases take 1.43 s.
  > ⚠️ **The Milvus-up number is load-sensitive.** On 2026-11-25, right after an index rebuild plus
  > a Docker image rebuild (machine under load), the same suite measured **19.3–21.3 s**; it dropped
  > back to 7.5–8.9 s once the machine settled. Re-measured 2026-11-27 under load: **21.9–22.9 s**.
  > This is **not** the code change and **not** the model switch — two candidate explanations were
  > tested and ruled out: ① cold vs warm Ollama model makes no difference (unload bge-m3 first →
  > 7.83 s; warm → 7.72 s); ② `import main` is not the culprit (`OllamaEmbeddings()` construction:
  > 0.46 s bare, 0.48 s after importing `main`). **Always qualify the number with "machine load".**
- **Coverage gap**: the fast suite *does* run `graph.invoke()` — routing branches, counter-reset
  semantics and reflect decisions have 17 cases in `test/test_agent_flow.py` plus a parametrized
  "dangling `tool_calls` == 0" net. What is **not** covered: the reflect prompt's hard constraint
  ("never answer `re_iterate` after a tool timeout/error") — a scripted fake reflect cannot exercise
  it. See `docs/status/测试体系.md` §6.

`test/README.md` is the per-file index: what each script tests, its measured result, and what the
suite does *not* cover. Read it before adding or running anything under `test/`.

## Runtime Architecture

### Frontend and API layer

`main_web.py` provides three Streamlit pages: Agent smart Q&A (backed by `/agent/chat`), direct
knowledge-base Q&A (`/rag`), and repository administration for document upload.

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
**~0.42 s of it is building the embedding HTTP client**, i.e. two httpx clients each building an
SSL context; plus YAML reads and two health-check RPCs), while the actual retrieval only
takes ~0.10 s. A failed connection is **not cached**, so the next request retries.
See `api/dependencies.py`.

Note: this is **not** "a new Milvus gRPC connection per request" — pymilvus 2.6 has its own
`ConnectionManager` that caches the underlying gRPC channel per address (a second client
costs 0.000 s). The repeated cost is the embedding client plus config/health-check overhead.

The Agent path is intentionally decoupled from `app.state.model_manager`:

- `api/api_agent.py` calls `agent.runtime.ask()`.
- `agent.runtime` lazily compiles and reuses the LangGraph graph.
- All three LLM nodes (`iter` / `synth` / `reflect`) explicitly create `MiniMax-M3.1-Flash` rather than using the YAML default model.
- `session_id` is passed as a LangGraph `thread_id`, but the graph has no checkpointer. Agent multi-turn persistence is therefore not implemented.

## LangGraph Agent (v2.2)

Single-Agent, multi-tool, ReAct-style graph with an LLM-as-judge reflection step. v2.2 replaced
v2.1 to fix three bugs: the dual-role node, mixed-up counters, and the tool-timeout deadlock.

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

**超时只有两层计时**，另有一条与计时正交的错误语义线 —— 三者职责不重叠：

```text
第 1 层  单次动作超时 agent/timeout.py :: Timer
         Timer(TOOL_TIMEOUT).call(fn, ...) —— 超时抛 AgentTimeoutError

第 2 层  整图总时限   state["deadline"] + agent/timeout.py :: is_expired()
         runtime.ask() 写入 deadline = time.time() + TOTAL_TIMEOUT
         每个节点动手前协作式检查，超时就地收手

错误语义  agent/errors.py（不计时，与上面两层正交）
         AgentError / AgentTimeoutError（可重试） / AgentToolError（不可重试）
         工具层把第三方异常翻译成自家异常，只翻译一次
```

分层的理由是"职责不重叠"：第 1 层管"这一次等多久"、第 2 层管"整张图还能跑多久"、
错误归一化管"错误叫什么"。**别把归一化算成超时层** —— 它不计时，
只决定这个失败值不值得重试。

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
    messages: Annotated[list, add_messages]           # reducer 1
    iter_count: Annotated[int, _inc_iter]             # reducer 2
    reflection_count: Annotated[int, _inc_refl]        # reducer 3
    tool_status: Annotated[dict, _merge_tool_status]  # reducer 4 — key=调用 id
    last_critique: str
    next_action: str      # reflect 的决策：end / rewrite / re_iterate
    deadline: float       # 图级总时限（绝对时间戳）
    expired: bool         # 已超时标志 → 条件边直接 END
    last_answer: str      # synth 最近一次写出的答案（超时兜底时交出去）
```

9 个字段，**4 个 reducer**。字段必须显式声明，否则 LangGraph 不会把它写进 state（`next_action` 曾经因此恒为缺省值）。**未声明 reducer 的字段默认是覆盖（LastValue），不是累加** —— 这是 LangGraph 最容易踩的默认值。
`last_answer` 不能靠"倒着找最后一条 AIMessage"推导 —— messages 里混着 iter 的占位消息（`"READY"`），
会把占位消息当成答案交出去。

### Runtime

`agent.runtime.ask()` debug 模式返回 5 字段：`answer` / `iter_count` / `reflection_count` / `tool_called` / `last_action`。`api/api_agent.py` 仍调 `ask()` 非 debug 模式。

`runtime.py` 显式给 LangGraph `recursion_limit`，**从常量推导、不写死**（`runtime.py:24-25`）：
`_STEPS_PER_ROUND = 2*MAX_ITER + 2` = 8，`RECURSION_LIMIT = 8 * (MAX_REFL+1) + 10` = **42**。
最坏情况 8 步/轮 × 4 轮 = **32 步 > 默认上限 25** → 不推导就会撞 `GraphRecursionError`，被 `ask()` 的 except 吞成"agent 调用异常"。

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

## Answer-quality evaluation (线 A / 线 B)

`test/eval_quality/` — **两条只读的评测线，不改生产代码**。线 A 直接调生产 `build_graph()`
（`ask()` 只返回 5 个字段，拿不到工具调用与召回片段）；线 B 直接调生产
`reflect_node(state, llm=…)`（`reflect_ablation_eval.py:117` `build_state` / `:154` `run_case`）。
改的是"喂什么进去"，不是"生产逻辑"。

**线 A** — 端到端答案质量，12 题 × 3 遍 = 36 个答案。口径：`hit_rate`（`must_contain`
必答命题，权重 0.6）/ `halluc`（命中 `must_not_contain` 负例 → **该题封顶 0.5**，权重 0.3）/
`retrieval_hit`（权重 0.1）；`depth_rate`（`should_contain`）**不进总分**，单独报。
总分 = **A/B 组 8 题**的 `score` 均值；C/D 组不进总分。

**线 B** — 反思消融，48 格 × 3 遍 = 144 次判定。48 格 = 4 题 × 6 种答案（good×2 / 矛盾 /
缺项 / 答非所问 / 编造）× 2 种素材（标准 / 无关）。`classify()`（`:195`）**先看
`action == "re_iterate"`** —— 生产 prompt 里 `re_iterate` 的语义是"素材不够、要再查"
（`agent/prompts/reflect_prompt.py:53`），不是"答案错"，于是 24 格无关素材全部落进
"素材充分性"轴，**三个指标的分母都只用标准素材**。

### Measured (2026-11-27)

> ⚠️ **尺子保持 v4（`rubric_version: v4-2026-11-27`），本轮没有升版。**
> 2026-11-28 只做了一件事：**把"超时是三层计时"这个错误口径，在代码与文档里改成
> 「两层计时 + 一条正交的错误语义线」**（`agent/timeout.py` 的 docstring 原文写的就是「两种计时」，
> 错的是文档把错误归一化算成了第三层）。改的是 `README.md` / `CLAUDE.md` / `docs/status/*` /
> `agent/errors.py` 的**表述**，没碰生产逻辑、没碰语料、没碰评测尺子。
> ⚠️ **语料是冻结的**（`documents/` + `txt/` 停在 2026-11-27，`corpus_sha256` = `eae9bb07…`，
> Milvus alias `txt_data` → `txt_data_1795716420` 2181 行，与之完全一致）→ **不重建索引、不重跑**。
> 冻结语料里的项目描述仍是**旧的三层口径**（知识库没随代码迭代），评测尺子 v4 与它**同口径** →
> **线 A 的数字继续可比、尺子继续可跑**；**线 B 不受影响**
> （标准素材内嵌在 `reflect_ablation_cases.json` 里，不查 Milvus）。
> ⚠️ **已知代价**：代码/文档说"两层"，语料/尺子说"三层" —— 有意保留，换的是语料指纹和数字可比性。

| | 值 | 稳不稳 |
|---|---|---|
| 线 A 总分 | **0.9333**（0.9125 / 0.9625 / 0.9250，极差 0.05） | ⚠️ 不稳 |
| 线 A `hit_rate` | 0.9305（67/72，极差 0.1667） | ⚠️ 不稳 |
| 线 A `depth_rate`（不进总分） | 0.8333（15/18，极差 0） | ✅ 稳 |
| 线 A 幻觉 / 检索命中 | 1 例（B03）/ 0.8333 | — |
| 线 B 真阳性率 | **100%（36/36，极差 0）** | ✅ **可当稳定结论** |
| 线 B 假阳性率 | **33.3%（8/24，极差 12.5 pp）** —— 8/8 全是「引用」规则，不是忠实性误报 | ✅ 稳（**要主动说**） |
| 线 B 不可判定率 | 0%（0/12） | ✅ 稳 |
| 线 B 改后改善（真·坏答案） | **+0.5139**（11/12 变好，幻觉修好 3 例） | ⚠️ 单次采样 |
| 线 B 改后**误伤**（好答案被误改） | **−0.1667** | ⚠️ 单次采样 |
| 线 B 改后**净值** | **+0.2895**（19 格） | ⚠️ **净值掩盖结构，两条要分开报** |
| 闭卷对照 | 8 题 0.1667 vs 带检索 0.9444（**8/8 全更低**） | 题库未被"先验可猜"污染 |

⚠️ **线 A 的 0.9333 会高估** —— `depth_rate` 和 C/D 组都不进总分；且线 A 的波动来自**真实
检索端**（Agent 每次改写查询 → 召回不同），**多跑几遍不会收敛，不能当稳定基线**。
线 B 的四个指标可以当稳定结论 —— 两次独立的 3 遍跑**逐格判定向量 48/48 完全相同**，
但 critique 措辞 144/144 都不同（证明是独立采样，不是缓存）。

### Rules for this evaluation system

1. **快照永不覆盖** —— 同名文件自动加 `-2` / `-3` 后缀。每份快照带 `corpus_sha256` /
   `git_commit` / `rubric_version` / `executor_model` / `judge_model` / `cases_hash`。
   快照**入库跟踪**（`test/eval/data/` 与 `test/eval_quality/results/` 同口径）——
   数字可以被第三方从原始 JSON 复算。
2. **`corpus_sha256` 是"这份数字量的是哪份语料"的标签，不是"语料不许变"** —— hash 相同 =
   数字可直接比；hash 不同 = **两份数字不可直接比**。换语料要重建索引
   （`python -m utils.txt_spliter.vector_main`，当前语料 14 个文件，嵌入模型 0 token，
   约 14 分钟）→ 重跑并另存快照。
   ⚠️ **本仓库有个具体耦合**：`documents/` 里躺着 `docs/status/*.md` 的副本（A/B 组 8 道题
   问的就是项目自己的实现细节）→ **改完 status 文档再重建索引 = 换了语料** → 线 A 要重跑。
3. **判分器与执行体跨模型隔离** —— 判分器 **MiniMax-M2.5**、执行体 **MiniMax-M3.1-Flash**，
   避免"自己给自己打分"。
4. **判分器不能用 `with_structured_output`** —— M2.5 会先吐 `<think>…</think>` 再吐 JSON，而
   `ThinkingStripRunnable`（`agent/llm_wrapper.py:103`）剥 think 剥得太晚（Pydantic 解析发生在
   `ChatOpenAI` 内部）→ 必然 `ValidationError`。判分器走**普通 `.invoke()` → `strip_thinking()`
   → 自己抽 JSON**（`judge_answer_quality.py:120`）。
5. **判分器故障 ≠ 答案错** —— 判分器异常时该题记 `judge_error`，**不计分母、不记 0**。
6. **嵌入模型 0 token** —— 索引 / 向量化不花钱，只有生成与判分花 LLM token。
7. **正则口径的"假阳性"要单独查** —— C01 的 `fabricate_regex` 曾把「需进一步查看
   `redis://` 等配置」误判为编造（v4 已收紧成"必须像真地址"）。收紧后 C01 变成 2/3 通过，
   剩下那 1 次是**真失败**。

### What these evaluations found (2026-11-27)

量出了四个此前未知的缺陷，全部登记在 `docs/status/项目现状.md` §8（**只登记未修**）：

| 缺陷 | 症状 | 复现性 |
|---|---|---|
| **P1-11** synth 的 LLM 超时无降级路径，兜底文案把内部异常类名交给用户（`agent/nodes/synth_node.py:81` → 「综合答案生成失败：APITimeoutError」） | 该题 `must_hit` 0/4，单题拉低总分 0.08；耗时 96.5 s vs 33/37 s；工具侧 4 次调用全 `success` → 根因是 `timeout.llm: 30` 对长上下文综合不够 | **偶发**（36 次里 1 次） |
| **P2-10** Agent 改写查询时丢掉否定语义 | B02 问「**为什么不能**直接返回空列表」，改写后"不能"丢了 → `retrieval_hit` 3/3 遍恒 0；而**直接** `rag.retrieve(query)` 的召回准入 10/10 全过 | **稳定 3/3**，重跑不会变好 |
| **P2-9** 占位工具的「占位：」标记在综合阶段被剥掉 | C02 三遍里两遍把占位天气当真实天气报出去 → **众数 = 失败** | **3 遍里 2 遍失败** |
| **P2-11** reflect 的「引用」规则太严 | 假阳性 33.3%，8/8 的 critique 都明说"内容与素材一致"、只嫌没标引用 → 好答案被误改平均 −0.17 | **稳定 8/24** |

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

**`configs/` is baked into the Docker image, not bind-mounted.** The `api` service mounts only
`./documents` and `./txt`; `Dockerfile` does `COPY . .`, so the container reads the
`model_config.yaml` that existed when the image was built. Changing a config file therefore
requires `docker compose build api` + `up -d --force-recreate` — a plain restart is not enough.
Measured 2026-11-25: the container kept the old `bge-large` while the index was rebuilt with
`bge-m3`; both embedders are 1024-dimensional, so Milvus raised nothing and the container
answered "the document does not contain…" while the host answered "three years" — a silent
answer-quality divergence, not a crash. Verify with
`docker exec ragmi-api python -c "from utils.models.embedding_model import EmbeddingModel; print(EmbeddingModel()._resolve_model_name())"`.

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
- The embedding model name comes from `EmbeddingModel._resolve_model_name()` only (`EMBEDDING_MODEL` env var > YAML). Never hardcode the model name (currently `bge-m3`) — a silent mismatch with the indexing side returns noise, not an error.
- Do not build a second `OllamaEmbeddings` in `core/rags/rags.py`; reuse `EmbeddingModel.embedding` so the timeout and the model name stay in one place.
- Always construct `MilvusClient` with `uri=f"http://{host}:{port}"`. pymilvus 2.6 has no `host`/`port` parameters — those keys fall into `**kwargs` and are **silently ignored**, so the client connects to the default `http://localhost:19530`. That happens to work on the host and always fails inside a container.
- `requirements.txt` is a **fully pinned lock file** (140 packages, closure resolved with linux markers). Pinning only direct dependencies lets transitive deps drift to newer versions and break the container at import time. To change a dependency: edit the "直接依赖" section, then re-resolve the closure — do not hand-edit the locked section.
- `get_rag_model` (`api/dependencies.py`) is an **app-level singleton** on `app.state.rag_model`. FastAPI's `Depends` cache does not span requests, so building a `RagModel` per request costs a new Milvus gRPC connection every time.
- Treat Agent `session_id` as non-persistent until a LangGraph checkpointer is added.
- `api/api_file.py` is mounted under `/api`, so its effective upload endpoints are `/api/upload-and-parse` and `/api/batch-upload-and-parse`.
- When adding or removing API modules, update or satisfy `test/test_main_routes_covered.py`; it exists to prevent unmounted `api_*.py` dead code.
- When changing `agent/` behavior, add or update a case in `test/test_agent_flow.py` (graph / flow) or `test/test_agent_timeout.py` (timeout / exception mechanism); when changing a tool's body, add or update a case in `test/test_tools.py`. The scripts under `test/archive/` are dead scaffolding and are not pushed to the repo; the two live offline evaluations are `test/eval/run_agent_eval.py` (routing) and `test/eval_quality/` (answer quality + reflection ablation).
- The Agent's internal placeholder messages are defined once in `agent/constants.py` (`SIGNAL_READY` / `SIGNAL_MAX_ITER` / `SIGNAL_EXPIRED`, grouped as `INTERNAL_SIGNALS`). Producers and consumers must reference the constants, never the string literals — a copied literal drifts and turns the "the answer is not a placeholder" assertion into a tautology.
- `calculator` must never use `eval()`. It evaluates a hand-rolled AST whitelist (`agent/tools/calculator_tool.py`); keep `test/test_tools.py` green if you touch it.
- The frontend reads `API_BASE_URL` (default `http://localhost:8000`) — all three `web_page/*.py` files. Do not hardcode a backend address again; the previous mix of `localhost:8000` and `api:8000` broke container deployments.
- **Do not re-run the answer-quality evaluations just to "refresh" a number.** Snapshots are the record; re-running produces a different number that means nothing and costs money. Only re-run when the rubric, the corpus, or the production behavior changed — and then save a **new** snapshot.

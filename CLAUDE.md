# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
# The README notes that Milvus may need about 90 seconds before it is healthy.
docker-compose -f docker-compose-milvus.yml up -d
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
# Unit tests plus mock-mode Agent evaluation
make test

# Reflection unit tests only
make test-unit

# Agent evaluation in mock mode
make test-mock

# Agent evaluation with the configured real model/API
make test-eval

# Entire pytest-discovered suite
pytest

# One test file
pytest test/test_reflect.py -v

# One test function
pytest test/test_reflect.py::test_name -v

# Router-mount regression test
pytest test/test_main_routes_covered.py -v

# Direct evaluation commands
PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py --mock
PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py
```

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

The Agent path is intentionally decoupled from `app.state.model_manager`:

- `api/api_agent.py` calls `agent.runtime.ask()`.
- `agent.runtime` lazily compiles and reuses the LangGraph graph.
- Both the Agent node and reflection node explicitly create `MiniMax-M3` rather than using the YAML default model.
- `session_id` is passed as a LangGraph `thread_id`, but the graph has no checkpointer. Agent multi-turn persistence is therefore not implemented.

## LangGraph Agent (v2.2)

The Agent is a single-Agent, multi-tool ReAct-style graph with an LLM-as-judge reflection step. v2.2 替换 v2.1 解决 3 个 bug：节点层双角色 / counter 混叠 / 工具超时死循环。

```text
START → iter
          ├─ tool_calls present → tools → iter (loop)
          └─ no tool call (incl. "READY" / 乱码 / iter_count ≥ MAX_ITER) → synth

synth
  ├─ synth_count < MAX_SYNTH → 写答案 → reflect
  └─ synth_count ≥ MAX_SYNTH → 强制 END

reflect
  ├─ end → END
  ├─ rewrite → synth（synth_count 已重置）
  ├─ re_iterate → iter（iter_count 已重置）
  └─ reflection_count ≥ MAX_REFL → 强制 end（兜底防死循环）
```

### 4 节点 vs v2.1 3 节点

v2.1 节点：`agent`（决策+综合双角色）/ `tools` / `reflect`

v2.2 节点：`iter`（纯决策，不写答案）/ `tools` / `synth`（综合）/ `reflect`

分离原因：v2.1 agent_node 同时承担"决定要不要调工具"和"写最终答案"两种 LLM 模式，互相干扰。v2.2 拆为 2 个节点 + `iter` 用 `READY` 信号交接。

### 3 counter vs v2.1 单 counter

v2.1：`iterations`（单计数器，混叠 agent_node 决策+综合次数，导致反思触发条件短路）

v2.2：`iter_count` / `synth_count` / `reflection_count` 三个独立计数器，各管自己的节点：

- `iter_count` — iter 节点调用次数，上限 `MAX_ITER=3`，reflect rewrite/re_iterate 时重置
- `synth_count` — synth 节点调用次数，上限 `MAX_SYNTH=2`，reflect 时重置
- `reflection_count` — reflect 节点调用次数，上限 `MAX_REFL=3`，**永不重置**（绝对上限，防死循环）

### 工具状态（防死循环 bug）

`StatusToolNode(ToolNode)` 包装 LangGraph ToolNode，写 `state["tool_status"]` 字典：

| 值 | 触发条件 |
|---|---|
| `success` | 工具返回非空内容 |
| `empty` | 工具返回空字符串 |
| `timeout` | 工具抛 TimeoutError |
| `error` | 工具抛其他异常 |

reflect prompt 硬约束：工具 timeout/error 时不应判 `re_iterate`（否则 `iter → tools(超时) → iter` 死循环）。即便 LLM 误判，`MAX_REFL=3` 兜底强制 end。

### 配置

`configs/agent_config.yaml` 定义 `MAX_ITER` / `MAX_SYNTH` / `MAX_REFL`。`agent/constants.py` 加载并导出，启动时 assert 校验。

### 工具清单

4 个：`rag_search`（已有）/ `calculator` / `weather` / `web_search`（3 个占位实现）。

### 节点细节

- `agent/nodes/iter_node.py`：`bind_tools(ALL_TOOLS)`，prompt 强制"不调工具时输出 READY"，含 try/except + `iter_count >= MAX_ITER` 边界检查
- `agent/nodes/synth_node.py`：不挂 `bind_tools`，按 `state["last_critique"]` 是否空切换 prompt 模式（首次 vs 重写），含 try/except + `synth_count >= MAX_SYNTH` 边界检查
- `agent/nodes/reflect_node.py`：用 `with_structured_output(ReflectOutput)`，Pydantic 解析；失败 fallback `next_action=rewrite`；超 `MAX_REFL` 强制 end；rewrite/re_iterate 时重置 iter/synth count
- `agent/nodes/status_tool_node.py`：包装 `ToolNode`，4 种 status 值 + ToolMessage 兜底（避免 graph 卡在 tool_calls 未应答）
- `agent/nodes/should_continue.py`：含 2 个条件边函数（`should_continue` + `after_reflect`）

### 状态 Schema

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    iter_count: Annotated[int, _inc_iter]
    synth_count: Annotated[int, _inc_synth]
    reflection_count: Annotated[int, _inc_refl]
    tool_status: Annotated[dict, _merge_tool_status]
    last_critique: str
```

### Runtime

`agent.runtime.ask()` debug 模式返回 6 字段：`answer` / `iter_count` / `synth_count` / `reflection_count` / `tool_called` / `last_action`。`api/api_agent.py` 仍调 `ask()` 非 debug 模式。

### 错误和调试

`ask()` 仍捕获 graph 调用异常返回友好消息（不抛 HTTP 500）。`ask()` debug=True 返回 dict 含 `last_action` 字段（end / rewrite / re_iterate / error）。

## RAG and Vector Storage

`core/rags/rags.py` owns the reusable retrieval pipeline:

1. Create the configured embedding/Milvus settings through `EmbeddingModel`.
2. Embed queries with `langchain_ollama.OllamaEmbeddings` using `bge-large` at `localhost:11434`.
3. Search the configured Milvus collection/alias for the top five chunks.
4. Either return chunks through `retrieve()` or build a grounded prompt and generate through `chat()`.

`utils/txt_spliter/vector_main.py` rebuilds vector data safely:

1. Parse all files available through the splitter.
2. Generate embeddings by calling Ollama `/api/embed` directly in batches.
3. Create a timestamped collection such as `<alias>_<timestamp>`.
4. Insert chunks and build an `AUTOINDEX` cosine index.
5. Atomically create or move the stable alias from `configs/model_config.yaml`.
6. Leave the old collection intact for manual cleanup or rollback.

Do not replace the direct Ollama HTTP embedding path in `vector_main.py` with `langchain_ollama` without investigating its documented local proxy/port issue. Note that query-time retrieval in `core/rags/rags.py` still uses `langchain_ollama`, so indexing and querying currently use different clients for the same embedding model.

## Configuration

`configs/model_config.yaml` defines Ollama, Alibaba Cloud, OpenAI-compatible, and MiniMax platforms plus Milvus/text-splitting settings. Environment placeholders are resolved from `.env`; important variables include:

- `MINIMAX_BASE_URL`, `MINIMAX_API_KEY`
- `ALIYUN_BASE_URL`, `ALIYUN_API_KEY`
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`
- `MILVUS_HOST`, `MILVUS_PORT`
- optionally `OLLAMA_BASE_URL`, `EMBEDDING_MODEL`

The YAML default model is not the Agent model: direct chat/RAG use the managed current model, while Agent and reflection explicitly select MiniMax-M3.

## Important Constraints

- Keep Agent tool output as raw retrieved chunks; final synthesis belongs to the Agent LLM.
- Make Agent routing changes in the graph, prompts, tool schema, or conditional edges—not by reintroducing the removed custom JSON/confidence router.
- Preserve both loop guards when modifying graph routing.
- Treat Agent `session_id` as non-persistent until a LangGraph checkpointer is added.
- `api/api_file.py` is mounted under `/api`, so its effective upload endpoints are `/api/upload-and-parse` and `/api/batch-upload-and-parse`.
- When adding or removing API modules, update or satisfy `test/test_main_routes_covered.py`; it exists to prevent unmounted `api_*.py` dead code.

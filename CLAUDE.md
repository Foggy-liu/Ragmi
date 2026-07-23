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

## LangGraph Agent

The Agent is a single-Agent, single-tool ReAct-style graph with an LLM-as-judge reflection step.

```text
START → agent
          ├─ tool_calls present → tools → agent
          ├─ no tool call       → reflect
          └─ iterations >= 5    → END

reflect
  ├─ sufficient             → END
  └─ insufficient           → append critique → agent
```

### Nodes and routing

- `agent/graph.py` builds a `StateGraph(AgentState)` with `agent`, `tools`, and `reflect` nodes. `tools` is LangGraph's `ToolNode([rag_search])`.
- `agent/nodes/agent.py` prepends `SYSTEM_PROMPT`, invokes `MiniMax-M3.bind_tools([rag_search])`, and appends either an answer or an AI message containing standard tool calls.
- `agent/nodes/should_continue.py` routes tool calls to `tools`; responses without tool calls go to `reflect`; the iteration limit ends the graph.
- `agent/nodes/reflect.py` asks another MiniMax-M3 invocation to return `is_sufficient` and `critique`. Parsing uses direct JSON, JSON-object extraction, then a fail-safe insufficient result.
- A failed reflection appends `AIMessage("反思意见：...")`, which becomes context for one more Agent answer.

### State and limits

`agent/state.py` defines the shared state:

- `messages`: merged with LangGraph `add_messages`.
- `iterations`: incremented each time `agent_node` runs; `MAX_ITERS = 5`.
- `reflection_count`: incremented by `reflect_node`; `MAX_REFL = 1`.
- `last_reflection_pass`: controls the edge after reflection.

When the reflection limit is reached, `reflect_node` forces a pass to prevent another loop. `iterations` counts Agent-node invocations, not only tool-use cycles.

### Tool semantics

`agent/tools/rag_tool.py` exposes only `rag_search(query)`:

- It lazily creates one `RagModel`.
- It calls the public `RagModel.retrieve(query, top_k=5)` method.
- It returns raw chunks separated by `---`.
- The Agent LLM, not `RagModel.chat()`, synthesizes the final Agent answer.

Tool selection uses LangChain/LangGraph standard Function Calling through `bind_tools()`. There is no custom `{tool, confidence, reasoning}` response parser, confidence threshold, regex tool router, or separate `ChatTool`. If no tool is required, the Agent LLM answers directly.

`agent/prompts/system_prompt.py` requires RAG answers to remain grounded in retrieved chunks and to admit when the chunks lack the answer.

### Error and debug behavior

`agent.runtime.ask()` catches graph invocation exceptions and returns a fixed friendly message instead of propagating an HTTP 500. This is a general exception fallback; it does not implement RAG retry or fallback-to-chat behavior.

With `debug=True`, `ask()` returns:

```text
answer, iterations, reflection_count, score, tool_called
```

The HTTP `/agent/chat` route currently calls `ask()` without debug mode and returns only `response`.

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

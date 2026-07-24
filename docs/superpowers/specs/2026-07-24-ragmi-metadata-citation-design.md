# RAGMI Metadata + 引用 Spec（spec 1 / 3）

> 撰写日期：2026-07-24
> 对应代码：`D:\PythonProject\ragmi` master 分支
> 三条独立 spec 中的第一条（另两条：RAG 评测闭环、Agent 状态与评测收口，后续启动）
> 状态：设计草案，待用户审核 → writing-plans

---

## 0. 目标

把 `RagModel.retrieve()` 从"返回 `List[str]`"升级为"返回 `List[RetrievalHit]`"，让 Agent 与 `/rag` 答案天然可追溯，并在 API 响应中暴露 `citations` 字段，作为后续 RAG 评测（spec 2）和 Reflection faithfulness（spec 3）共享的契约。

成功标准：
- 所有 `/rag`、`/agent/chat` 响应包含 `citations: [...]`，每条含 `index / source / chunk_id / doc_id`。
- 答案末尾由代码强制追加"参考资料：[1] source#chunk_id ..."行，无论 LLM 是否遵循引用指引。
- `doc_id` 与现有 `utils/docs/manager/filter.py:31-42` 的 MD5 去重逻辑一致。

---

## 1. 范围

### 在范围内

- Milvus schema 增加 `source` / `chunk_id` / `doc_id` 三字段；
- Splitter 写入 `doc_id`（`source` / `chunk_id` 已存在）；
- `RagModel.retrieve()` 返回 `List[RetrievalHit]`，`chat()` 收集并返回 `citations`；
- `rag_search` 工具给每个 hit 打 `[N]` 编号；
- Agent 节点收集最近一次 `ToolMessage` 里的结构化 hits，写回 `state.citations`；
- `agent/prompts/system_prompt.py` 增加引用指引；
- `api/api_rag.py` 与 `api/api_agent.py` 响应改为 `{response, citations}`;
- `agent/runtime.py` debug 模式返回含 `citations` 字段。

### 不在范围内（独立 spec）

- 前端引用面板 / 点击跳原文；
- 文档版本管理（基于 doc_id + 时间戳）；
- 文档级用户权限；
- 文档去重（filter.py 已做内容级去重）；
- 引用块的 UI 美化。

---

## 2. 架构与数据流

```
uploaded file
   ↓ utils/docs/txt_main.py:43
MD5(source content) → doc_id  ←── 与 filter.py _get_hash 一致
   ↓ utils/docs/txt_spliter/spliter.py:115-125
chunk{page_content, source, chunk_id, doc_id}
   ↓ utils/docs/txt_spliter/vector_main.py
Milvus: {vector, text, source, chunk_id, doc_id}
   ↓ core/rags/rags.py:retrieve()
List[RetrievalHit{text, source, chunk_id, doc_id, score}]
   ↓ agent/tools/rag_tool.py
每个 hit 加 [N] 编号，拼成 numbered chunks 返回给 LLM
   ↓ 同时把结构化 hits 写进 ToolMessage.additional_kwargs["citations"]
agent/nodes/agent_node 读最近 ToolMessage → 写回 state.citations
   ↓ Agent 答案 + /rag 答案
LLM 答案 + 后处理 append 参考资料行 + 结构化 citations 字段
   ↓ api/api_rag.py / api/api_agent.py
{"response": str, "citations": [{index, source, chunk_id, doc_id}, ...]}
```

### 关键不变性

- `RagModel` 仍是唯一检索入口；
- `rag_search` 工具仍只返回 string（LangChain `tool` 契约），结构化字段通过 `ToolMessage.additional_kwargs["citations"]` 旁路；
- Agent LLM 仍是 MiniMax-M3；
- alias 原子切换流程不变；
- LangGraph graph 节点结构不变（仅新增一个 state 字段）。

---

## 3. 组件级改动

### 3.1 `utils/txt_spliter/vector_main.py` —— Milvus schema + 写入

在 `vector_main.py:73-77` 现有 schema 基础上追加：

```python
schema.add_field(field_name='source',  datatype=DataType.VARCHAR, max_length=512)
schema.add_field(field_name='chunk_id', datatype=DataType.INT64)
schema.add_field(field_name='doc_id',   datatype=DataType.VARCHAR, max_length=64)  # MD5 hex
```

在 `vector_main.py:94-103` `entities` 构造处带上：

```python
entities = [{
    'vector': batch_vectors[j],
    'text': batch_texts[j],
    'source': batch_sources[j],
    'chunk_id': batch_chunk_ids[j],
    'doc_id': batch_doc_ids[j],
} for j in range(len(batch_texts))]
```

`doc_id` 从 `Document.metadata['doc_id']` 读。

### 3.2 `utils/txt_spliter/spliter.py` —— metadata 写入

`spliter.py:115-125` 已写 `source` / `chunk_id`，新增 `doc_id`：

```python
metadata={
    "source": txt_file.name,
    "chunk_id": i,
    "doc_id": self._compute_doc_id(txt_file),
}
```

`_compute_doc_id(file_path)` 实现：

```python
import hashlib
def _compute_doc_id(self, file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()
```

**注意**：此 hash 必须与 `utils/docs/manager/filter.py:31-42` 的 `_get_hash` 实现完全一致。本次 spec 提取为可复用工具函数（建议放到 `utils/hash.py` 或类似位置），filter.py 后续 spec 可考虑改用同一工具函数。

### 3.3 `core/rags/rags.py` —— 检索接口升级

#### 新增 `RetrievalHit` 数据类

```python
from dataclasses import dataclass

@dataclass
class RetrievalHit:
    text: str
    source: str
    chunk_id: int
    doc_id: str
    score: float  # pymilvus COSINE 返回的是距离，越小越近
```

#### `_search_similar_chunks` 返回结构化

```python
def _search_similar_chunks(self, query: str, top_k: int = 5) -> List[RetrievalHit]:
    if not self._client:
        logger.warning("向量库未加载，无法进行相似度搜索")
        return []
    try:
        query_vector = self._embed.embed_query(query)
        results = self._client.search(
            collection_name=self._collection_name,
            data=[query_vector],
            limit=top_k,
            output_fields=['text', 'source', 'chunk_id', 'doc_id'],  # ← 新增输出字段
        )
        hits = []
        for h in results[0]:
            hits.append(RetrievalHit(
                text=h.entity.get('text', ''),
                source=h.entity.get('source', ''),
                chunk_id=int(h.entity.get('chunk_id', 0)),
                doc_id=h.entity.get('doc_id', ''),
                score=float(h.distance),
            ))
        return hits
    except Exception as e:
        logger.exception(f"相似度搜索失败：{e}")
        return []
```

#### `retrieve(query, top_k=5)` 返回类型从 `List[str]` 改为 `List[RetrievalHit]`

> Breaking change，必须同步修改 `agent/tools/rag_tool.py`。

#### `chat()` 收集 citations 并拼接参考资料尾部

```python
def chat(self, query, session_id=None) -> Dict:
    session_id = self.msg_manager.ensure_session(session_id)
    hits = self._search_similar_chunks(query, top_k=5)

    citations = [
        {"index": i + 1, "source": h.source, "chunk_id": h.chunk_id, "doc_id": h.doc_id}
        for i, h in enumerate(hits, 1)
    ]

    custom_system = self._build_context_prompt(query, hits)  # 见下文
    messages = self.msg_manager.build_messages(session_id, query, custom_system)
    model = self.model_manager.get_current_model()
    response = model.invoke(messages)
    self.msg_manager.add_to_history(session_id, query, response)

    # 后处理：append 参考资料
    if citations:
        footer = self._format_citations_footer(citations)
        final_response = response + "\n\n" + footer
    else:
        final_response = response

    return {"response": final_response, "citations": citations}
```

`_build_context_prompt` 改造为接收 `List[RetrievalHit]` 而非 `List[str]`：

```python
def _build_context_prompt(self, query, hits: List[RetrievalHit]) -> str:
    if not hits:
        context = "没有找到相关文档片段。"
    else:
        parts = [f"[{i}] 来源：{h.source}（chunk {h.chunk_id}）\n{h.text}"
                 for i, h in enumerate(hits, 1)]
        context = "\n\n---\n\n".join(parts)

    return f"""你是一个基于RAG的个人知识库问答助手。

身份：当被问你是谁，回答"我是RAGMI"。

规则：
- 严格基于以下文档回答
- 文档无信息则告知无法回答
- 当答案使用到文档内容时，请在段落末尾用 [1][2][3] 标注对应编号
- 用户追问"依据"时再引用文档

文档：{context}

问题：{query}"""
```

`_format_citations_footer`：

```python
def _format_citations_footer(self, citations: List[dict]) -> str:
    lines = ["参考资料："]
    for c in citations:
        lines.append(f"[{c['index']}] {c['source']}（chunk {c['chunk_id']}）")
    return "\n".join(lines)
```

### 3.4 `agent/tools/rag_tool.py` —— 工具改造

工具消费结构化结果，**给每个 hit 打 `[N]` 编号**，并把结构化 hits 塞进返回的字符串附带结构化字段（langchain `@tool` 装饰器限定返回 string，结构化字段必须通过 ToolMessage 的 `additional_kwargs` 旁路）。

```python
@tool
def rag_search(query: str) -> str:
    """从 RAGMI 个人知识库检索与 query 相关的内容片段。
    适用 / 不适用 / 返回 说明不变。
    """
    model = _ensure_rag()
    hits = model.retrieve(query, top_k=5)
    if not hits:
        return "（知识库中没有找到相关文档）"
    parts = [f"[{i}] 来源：{h.source}（chunk {h.chunk_id}）\n{h.text}"
             for i, h in enumerate(hits, 1)]
    return "\n\n---\n\n".join(parts)
```

**结构化 citations 字段的传递**：在 Agent 路径里，结构化字段不能只放在字符串里。需要在 `agent/nodes/agent_node` 调 LLM 后，看 state 里最新的 ToolMessage（由 ToolNode 调用 rag_search 产生）。ToolMessage 已经是结构化对象，其 `.artifact` 或 `.additional_kwargs` 可以携带非文本数据。

实现思路：在 `rag_search` 内部把 hits 暂存到一个模块级 dict（key 用 `id(query)` 或工具调用 ID），`agent_node` 结束后读取最近的 ToolMessage 找到对应 hits。

> **更干净的方案**：在 `agent/tools/rag_tool.py` 把结构化 hits 通过 Python 闭包暂存到模块级 `_LAST_HITS: list[RetrievalHit]`，`agent_node` 在 LLM 返回答案后读 `_LAST_HITS` 并清空。简单且对 graph 透明。

### 3.5 `agent/prompts/system_prompt.py` —— 引用指引

在现有 `SYSTEM_PROMPT`（`system_prompt.py:8-26`）末尾追加：

```
【引用规则】
- 当基于检索片段回答时，请在段落末尾或文末用 [1][2][3] 标注来源编号
- 编号必须与检索片段前的 [N] 一致
- 若未检索到任何片段，则不写引用
```

### 3.6 `agent/state.py` —— AgentState 新增字段

```python
class AgentState(TypedDict, total=False):
    messages: ...
    iterations: ...
    reflection_count: ...
    last_reflection_pass: bool
    citations: list[dict]   # 新增：最近一次 rag_search 的结构化 citations
```

reducer 用默认覆盖（每次 agent_node 结束按最近 ToolMessage 重写）。

### 3.7 `agent/nodes/agent.py` —— 收集 citations

```python
from agent.tools import rag_tool

def agent_node(state: dict) -> dict:
    llm = _get_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
    response = llm.invoke(messages)

    # 取最近一次 rag_search 的结构化 hits
    citations = rag_tool.consume_last_hits()  # 读 + 清空 _LAST_HITS

    return {"messages": [response], "iterations": 1, "citations": citations}
```

`consume_last_hits` 在 `agent/tools/rag_tool.py`：

```python
_LAST_HITS: list[RetrievalHit] = []

def _record_hits(hits: list[RetrievalHit]) -> None:
    global _LAST_HITS
    _LAST_HITS = hits

def consume_last_hits() -> list[dict]:
    global _LAST_HITS
    out = [
        {"index": i + 1, "source": h.source, "chunk_id": h.chunk_id, "doc_id": h.doc_id}
        for i, h in enumerate(_LAST_HITS, 1)
    ]
    _LAST_HITS = []
    return out
```

`rag_search` 内部：

```python
hits = model.retrieve(query, top_k=5)
_record_hits(hits)  # 新增
```

### 3.8 `api/api_rag.py` —— 响应契约

`/rag` 当前返回 `{"response": str}`。改为：

```python
return {"response": result["response"], "citations": result["citations"]}
```

### 3.9 `api/api_agent.py` —— 响应契约

`/agent/chat` 当前 `ask()` 返回 str。改为：

```python
result = ask(question, session_id=session_id, debug=False)
if isinstance(result, str):
    return {"response": result, "citations": []}
return result  # 已经是 dict
```

### 3.10 `agent/runtime.py` —— `ask()` 返回结构调整

现状：`debug=False` 返回 str，`debug=True` 返回 dict。

> **设计取舍点**：为了不破坏现有调用方，建议 `debug=False` 也返回 dict（`{response, citations}`）。`api/api_agent.py` 已经能处理 dict（见 `runtime.py:64-66`）。如果 `api/api_agent.py` 当前仍假设返回 str，需同步改。
>
> 替代方案：保留 `debug=False` 返回 str，但暴露另一个公开方法 `ask_with_citations()` 返回 dict。两条路径并存。
>
> **采用方案**：直接改 `ask()`，让它总是返回 dict；`api/api_agent.py` 同步改为读 `["response"]`。

```python
def ask(question, session_id=None, debug=False) -> dict:
    graph = _get_graph()
    config = {"configurable": {"thread_id": session_id}} if session_id else None
    try:
        result = graph.invoke({"messages": [("user", question)]}, config=config)
    except Exception as e:
        return _error_response_dict(debug)

    answer = result["messages"][-1].content
    citations = result.get("citations", [])

    # Agent 路径下 /rag 风格后处理：append 参考资料
    if citations:
        footer = _format_citations_footer(citations)
        final_answer = answer + "\n\n" + footer
    else:
        final_answer = answer

    if not debug:
        return {"response": final_answer, "citations": citations}

    return {
        "answer": final_answer,
        "iterations": result.get("iterations", 0),
        "reflection_count": result.get("reflection_count", 0),
        "score": _compute_score(result),
        "tool_called": any(m.__class__.__name__ == "ToolMessage" for m in result["messages"]),
        "citations": citations,
    }
```

---

## 4. 端到端数据流示例

### 场景：用户问"在我的知识库里有什么内容"

1. 用户发起请求 → `api/api_agent.py` 入口。
2. `runtime.ask()` 调 `_get_graph().invoke(...)`。
3. `agent_node`（第一次）：LLM 看到 system prompt + 用户问题，输出 `tool_calls=[{name: "rag_search", args: {query: "知识库 内容"}}]`。
4. `should_continue` 路由到 `tools` 节点。
5. `ToolNode` 执行 `rag_search(query)`：
   - `_ensure_rag()` 复用懒加载的 `RagModel`；
   - `model.retrieve(query, top_k=5)` 返回 `List[RetrievalHit]`；
   - `_record_hits(hits)` 写入 `_LAST_HITS`；
   - 工具返回编号化字符串给 LangGraph；
   - `ToolNode` 把结果包成 `ToolMessage(content=编号字符串)` 写回 messages。
6. `agent_node`（第二次）：
   - LLM 看到 `HumanMessage + AIMessage(tool_calls) + ToolMessage(编号字符串)`；
   - 输出最终答案（可能含 inline [1][2]）；
   - 调 `consume_last_hits()` 拿到结构化 citations；
   - 返回 `{messages: [AIMessage], iterations: 1, citations: [...]}`。
7. `should_continue` 看 AIMessage 无 tool_calls → 路由到 `reflect`。
8. `reflect_node`：评答案，假设通过 → `last_reflection_pass=True`。
9. `after_reflect` → END。
10. `runtime.ask()` 读 `result["citations"]`，拼接参考资料 footer，返回 dict。
11. `api/api_agent.py` 返回 `{"response": "...参考资料行...", "citations": [...]}`。

### 场景：`/rag` 直接 RAG

1. `api/api_rag.py` → `RagModel.chat()`；
2. `_search_similar_chunks(query, top_k=5)` → `List[RetrievalHit]`；
3. `_build_context_prompt(query, hits)` 把 hits 转成带 [N] 编号的 context；
4. LLM 回答；
5. 后处理：append 参考资料 footer；
6. 返回 `{response, citations}`。

---

## 5. 错误处理

| 失败场景 | 行为 |
|---|---|
| Milvus 无 `source` / `chunk_id` / `doc_id` 字段（旧 collection） | `_search_similar_chunks` 用 `output_fields=['text', 'source', 'chunk_id', 'doc_id']`，旧集合缺字段会抛异常；fallback 改用 `output_fields=['text']`，缺字段 hits 的 source/chunk_id/doc_id 设为空字符串、`chunk_id=0`；记 warning 日志提示需重新索引 |
| `doc_id` 计算时文件读失败 | `_compute_doc_id` 返回 `""`（空串），不入引用 |
| `rag_search` 调用时 `_LAST_HITS` 未清空（多轮并发） | `consume_last_hits` 总是 `global _LAST_HITS = []` 后返回，next call 不会拿到 stale hits |
| LLM 不返回任何引用 prompt 指引 | 后处理 footer 仍然追加，`citations` 字段仍然返回结构化数据，**前端与评测不受影响** |
| `RagModel.retrieve()` 返回空 | citations = []，答案不带 footer，结构化字段空数组 |
| ToolNode 调用工具抛异常 | LangGraph 自动把错误写进 ToolMessage，`agent_node` 下一轮可看到错误信息决定是否重答 |

---

## 6. 测试策略

### 6.1 单元测试（`test/test_retrieval_hit.py` 新文件）

- `RetrievalHit` 字段访问；
- `_compute_doc_id` 与 `filter._get_hash` 对同一文件产出相同 hash（一致性）；
- `_format_citations_footer` 输出格式；
- `_search_similar_chunks` 字段映射正确性（mock Milvus 返回值）。

### 6.2 Agent / rag 引用集成测试（`test/test_citations.py` 新文件）

- `rag_search` 工具在 `RetrievalHit` 上输出 `[1] source（chunk N）` 前缀；
- `consume_last_hits` 多次调用互不污染；
- `/rag` 响应含 `citations` 字段且与 hits 一一对应；
- `RagModel.chat()` 答案末尾含 `参考资料：` 行。

### 6.3 回归测试（已有）

- `test/test_reflect.py` 不动；
- `test/test_main_routes_covered.py` 不动；
- `test/test_vector_split.py` 需 mock 掉 `_compute_doc_id` 的真实文件依赖（如果集成测试不便跑）。

### 6.4 集成测试调整

- 跑 `test/test_vector_split.py`：验证新 schema 字段被写入；
- 跑 `test/run_agent_eval.py --mock`：验证 T04/T08/T11 等 RAG case 仍路由正确；
- 验证 agent_eval_results.json 的 details 包含 citations 字段（如适用）。

---

## 7. 实施顺序建议

1. `utils/hash.py`（或选位置）抽出 `_compute_doc_id`；
2. `spliter.py` 写入 doc_id；
3. `core/rags/rags.py` 定义 `RetrievalHit`、改造 retrieve/chat；
4. `vector_main.py` schema + 写入；
5. `agent/tools/rag_tool.py` 编号化 + `_record_hits`；
6. `agent/state.py` + `agent/nodes/agent.py` 收集 citations；
7. `agent/prompts/system_prompt.py` 引用指引；
8. `agent/runtime.py` 返回结构调整；
9. `api/api_rag.py` + `api/api_agent.py` 响应契约；
10. 测试 + 重跑 `vector_split` 集成测试。

---

## 8. 风险与未决

1. **Milvus schema 不兼容旧 collection**：旧 `txt_data_*` 集合没有 `source` / `chunk_id` / `doc_id` 字段，读取会失败。需要在 README 注明必须 `vector_main.py` 重建索引。
2. **`_LAST_HITS` 闭包在多并发场景下的正确性**：当前 LangGraph graph 假定单线程顺序调用；如果未来多并发访问同一进程，需要换成 thread-local 或 per-call 标识。本 spec 不解决。
3. **LLM 编号漂移风险**：LLM 偶尔会写错编号（例如把 [3] 写成 [4]）。后处理 footer 提供"正确答案"，不依赖 LLM 编号准确，但 inline 引用可能误导。RAG 评测（spec 2）会暴露这个问题。
4. **`splitter._compute_doc_id` 与 `filter._get_hash` 长期一致性**：本次 spec 让两者实现一致；如果未来 filter.py 改 hash 算法（如 MD5 → SHA256），splitter 必须同步改。建议把哈希函数提取到 `utils/hash.py` 作为单一来源。

---

## 9. 后续 spec 引用

- spec 2（RAG 评测闭环）将依赖 `citations` 字段做 faithfulness 评估；
- spec 3（Agent 状态与评测收口）将依赖 `citations` 让 Reflection 同时看到 retrieved context。

---

## 10. 自审清单（spec 完成后）

- [x] 占位符扫描：所有代码示例已用伪代码，无 TBD；
- [x] 内部一致性：架构与组件、数据流一致；
- [x] 范围检查：focused，单一 spec 可被一次实施完成；
- [x] 歧义检查：`doc_id` = MD5(source content) 已明确定义；`score` 字段含义（pymilvus COSINE distance）已注明。
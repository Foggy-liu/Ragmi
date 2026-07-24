# RAGMI Metadata + 引用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `RagModel.retrieve()` 从 `List[str]` 升级为 `List[RetrievalHit]`，让 Agent 与 `/rag` 答案天然可追溯，并在 API 响应中暴露 `citations` 字段。

**Architecture:** Splitter 写入 `doc_id`（MD5，与 `utils/docs/manager/filter.py` 一致）→ Milvus schema 加 `source` / `chunk_id` / `doc_id` 三字段 → `RagModel` 返回结构化 `RetrievalHit` → Agent / `/rag` 答案末尾由代码强制追加参考资料行 + 暴露结构化 `citations` 字段。

**Tech Stack:** Python 3.11+、FastAPI、pymilvus、langchain-core、langgraph；pytest 单测；现有 `make test` / `pytest -q` 入口。

---

## File Structure

### 新增文件

| 路径 | 职责 |
|---|---|
| `core/rags/types.py` | `RetrievalHit` dataclass 定义（text/source/chunk_id/doc_id/score） |
| `utils/hash.py` | `compute_md5(file_path)` 工具函数（与 `filter._get_hash` 实现一致） |
| `test/test_retrieval_hit.py` | `RetrievalHit` 字段访问与 `format_citations_footer` 输出格式测试 |
| `test/test_doc_id.py` | `compute_md5` 与 `filter._get_hash` 对同一文件产出相同 hash 的一致性测试 |
| `test/test_rag_citations.py` | `RagModel.chat()` 收集 citations + 拼接 footer 测试（mock LLM + Milvus） |
| `test/test_agent_citations.py` | `consume_last_hits` + `agent_node` 写回 `state.citations` 测试 |

### 修改文件

| 路径 | 改动 |
|---|---|
| `utils/txt_spliter/spliter.py:115-125` | chunk metadata 写入 `doc_id`（用 `utils.hash.compute_md5`） |
| `utils/docs/manager/filter.py:31-42` | `_get_hash` 复用 `utils.hash.compute_md5` |
| `utils/txt_spliter/vector_main.py:73-103` | Milvus schema 加 source/chunk_id/doc_id；插入字段带上 |
| `core/rags/rags.py:1-179` | 引入 `RetrievalHit`；`_search_similar_chunks` 返回结构化；`retrieve` 返回类型变化；`chat` 收集 citations + append footer；新方法 `format_citations_footer`、`_build_context_prompt` 接受 hits |
| `agent/tools/rag_tool.py:33-52` | 工具返回 `[N] source#chunk_id` 前缀；新增 `_record_hits` / `consume_last_hits` 模块级状态 |
| `agent/state.py:27-54` | `AgentState` 新增 `citations: list[dict]` 字段 |
| `agent/nodes/agent.py:37-56` | `agent_node` 调 `consume_last_hits` 并写回 `state.citations` |
| `agent/prompts/system_prompt.py:8-26` | 末尾追加【引用规则】段 |
| `agent/runtime.py:53-99` | `ask()` 返回 dict（含 `response` / `citations`），覆盖现有 str 返回 |
| `api/api_rag.py` | 返回 `{response, citations}` |
| `api/api_agent.py` | 读 `ask()` 返回的 dict 的 `response` 字段；返回 `{response, citations}` |

---

## Task 1: 抽取 `utils/hash.py` 并与 `filter._get_hash` 一致

**Files:**
- Create: `utils/hash.py`
- Modify: `utils/docs/manager/filter.py:31-42`
- Test: `test/test_doc_id.py`

- [ ] **Step 1: Write the failing test**

`test/test_doc_id.py`:

```python
"""test/test_doc_id.py —— utils.hash.compute_md5 与 filter._get_hash 一致性测试。"""
import tempfile
from pathlib import Path
from utils.hash import compute_md5
from utils.docs.manager.filter import FileFilter


def test_compute_md5_returns_hex_32():
    """MD5 hex 长度固定 32 字符。"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(b"hello ragmi")
        path = Path(f.name)
    try:
        h = compute_md5(path)
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)
    finally:
        path.unlink()


def test_compute_md5_matches_filter_get_hash():
    """compute_md5 与 FileFilter._get_hash 对同一文件产出相同 hash。"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(b"一致性测试内容")
        path = Path(f.name)
    try:
        h1 = compute_md5(path)
        # 用临时 output_dir 构造 FileFilter
        with tempfile.TemporaryDirectory() as tmp:
            ff = FileFilter(Path(tmp))
            h2 = ff._get_hash(path)
        assert h1 == h2, f"hash 不一致: {h1} != {h2}"
    finally:
        path.unlink()


def test_compute_md5_handles_missing_file(tmp_path):
    """文件不存在时返回空字符串（与 filter._get_hash 不同——它返回 None；本工具返回 ''）。"""
    missing = tmp_path / "no_such_file.txt"
    assert compute_md5(missing) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_doc_id.py -v`
Expected: ImportError: `utils.hash` 不存在 → FAIL。

- [ ] **Step 3: Create utils/hash.py**

`utils/hash.py`:

```python
"""utils/hash.py —— 文件内容哈希工具（与 utils/docs/manager/filter.py 一致）。

提供 compute_md5(file_path) 用于：
- Splitter 写入 chunk.metadata['doc_id']
- 后续 doc_id 与 filter._get_hash 同步（filter.py 复用本工具）
"""
import hashlib
from pathlib import Path


def compute_md5(file_path: Path) -> str:
    """计算文件内容的 MD5 hex digest。

    与 utils/docs/manager/filter.py FileFilter._get_hash 实现一致。
    文件读取失败时返回空字符串（区别于 filter._get_hash 返回 None）。

    Args:
        file_path: 文件路径（Path 对象）。

    Returns:
        32 字符的 MD5 hex digest；失败返回 ""。
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return ""
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (IOError, OSError):
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_doc_id.py -v`
Expected: 3 passed。

- [ ] **Step 5: Modify filter.py to reuse the new utility**

`utils/docs/manager/filter.py:31-42`，替换 `_get_hash` 实现：

```python
from utils.hash import compute_md5

class FileFilter:
    ...

    def _get_hash(self, file_path):
        """计算文件的MD5哈希值（与 utils.hash.compute_md5 一致）。"""
        result = compute_md5(file_path)
        return result if result else None  # 保持原 filter.py 失败返回 None 的契约
```

- [ ] **Step 6: Run all tests to verify no regression**

Run: `pytest test/test_doc_id.py test/test_reflect.py -v`
Expected: 全部 passed（filter.py 行为不变）。

- [ ] **Step 7: Commit**

```bash
git add utils/hash.py utils/docs/manager/filter.py test/test_doc_id.py
git commit -m "feat(hash): extract compute_md5 utility, share with filter.py"
```

---

## Task 2: 定义 `RetrievalHit` dataclass + format_citations_footer

**Files:**
- Create: `core/rags/types.py`
- Create: `test/test_retrieval_hit.py`

- [ ] **Step 1: Write the failing test**

`test/test_retrieval_hit.py`:

```python
"""test/test_retrieval_hit.py —— RetrievalHit 数据类与 format_citations_footer 测试。"""
from core.rags.types import RetrievalHit, format_citations_footer


def test_retrieval_hit_fields_accessible():
    """RetrievalHit 应支持 5 个字段访问。"""
    hit = RetrievalHit(
        text="hello",
        source="RAG入门.md",
        chunk_id=7,
        doc_id="abc123",
        score=0.12,
    )
    assert hit.text == "hello"
    assert hit.source == "RAG入门.md"
    assert hit.chunk_id == 7
    assert hit.doc_id == "abc123"
    assert hit.score == 0.12


def test_format_citations_footer_basic():
    """format_citations_footer 输出 '参考资料：\\n[N] source（chunk N）...'。"""
    citations = [
        {"index": 1, "source": "RAG入门.md", "chunk_id": 7, "doc_id": "abc"},
        {"index": 2, "source": "简历.md", "chunk_id": 3, "doc_id": "def"},
    ]
    out = format_citations_footer(citations)
    assert "参考资料：" in out
    assert "[1] RAG入门.md（chunk 7）" in out
    assert "[2] 简历.md（chunk 3）" in out


def test_format_citations_footer_empty():
    """空 citations 返回空字符串。"""
    assert format_citations_footer([]) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_retrieval_hit.py -v`
Expected: ImportError → FAIL。

- [ ] **Step 3: Create core/rags/types.py**

`core/rags/types.py`:

```python
"""core/rags/types.py —— RAG 检索相关数据结构定义。"""
from dataclasses import dataclass
from typing import List


@dataclass
class RetrievalHit:
    """单条检索命中。
    text:     原始 chunk 文本
    source:   源文件名（如 'RAG入门.md'）
    chunk_id: 在源文件内的 chunk 编号（int）
    doc_id:   源文件 MD5 hex digest（与 utils.hash.compute_md5 一致）
    score:    pymilvus COSINE 距离（越小越近；pymilvus search 返回的 h.distance）
    """
    text: str
    source: str
    chunk_id: int
    doc_id: str
    score: float


def format_citations_footer(citations: List[dict]) -> str:
    """生成参考资料底部文本。

    输入 citations 每条应有 index/source/chunk_id 字段。
    返回空字符串当 citations 为空。
    """
    if not citations:
        return ""
    lines = ["参考资料："]
    for c in citations:
        lines.append(f"[{c['index']}] {c['source']}（chunk {c['chunk_id']}）")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_retrieval_hit.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add core/rags/types.py test/test_retrieval_hit.py
git commit -m "feat(rags): add RetrievalHit dataclass and citation footer formatter"
```

---

## Task 3: Splitter 写入 doc_id 到 chunk metadata

**Files:**
- Modify: `utils/txt_spliter/spliter.py:115-125`
- Modify: `utils/txt_spliter/spliter.py:155-162` (split_file)
- Modify: `utils/txt_spliter/spliter.py:90-130` (split_all_files metadata)

- [ ] **Step 1: Write the failing test**

`test/test_splitter_metadata.py`（新文件）:

```python
"""test/test_splitter_metadata.py —— Splitter 写入 doc_id 测试。"""
import tempfile
from pathlib import Path

from utils.txt_spliter.spliter import Splitter


def test_split_writes_doc_id_in_metadata():
    """split_file 应在 Document.metadata 写入 doc_id（32 字符 MD5 hex）。"""
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".txt", mode="w", encoding="utf-8"
    ) as f:
        f.write("测试文档内容。" * 50)
        path = Path(f.name)
    try:
        s = Splitter()
        docs = s.split_file(str(path))
        assert len(docs) > 0
        for d in docs:
            assert "doc_id" in d.metadata
            assert len(d.metadata["doc_id"]) == 32
            # 与文件 hash 一致
            from utils.hash import compute_md5
            assert d.metadata["doc_id"] == compute_md5(path)
    finally:
        path.unlink()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_splitter_metadata.py -v`
Expected: AssertionError: 'doc_id' not in metadata → FAIL。

- [ ] **Step 3: Modify spliter.py to write doc_id**

`utils/txt_spliter/spliter.py`，在 `__init__` 之外但文件内顶部加 import：

```python
from utils.hash import compute_md5
```

修改 `split_file`（约 132-164 行），构造 Document 时添加 `doc_id`：

```python
def split_file(self, file_path: str) -> List[Document]:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    if file_path.suffix != '.txt':
        print(f"警告: 文件 {file_path.name} 不是txt文件")

    print(f"正在处理: {file_path.name}")

    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    chunks = self.split(text)
    doc_id = compute_md5(file_path)

    documents = []
    for i, chunk in enumerate(chunks):
        document = Document(
            page_content=chunk,
            metadata={
                "source": file_path.name,
                "chunk_id": i,
                "doc_id": doc_id,
            }
        )
        documents.append(document)

    return documents
```

修改 `split_all_files`（约 90-130 行）同样逻辑：

```python
def split_all_files(self) -> List[Document]:
    current_script_path = Path(__file__).resolve()
    input_dir = current_script_path.parent.parent.parent / "txt"
    input_dir.mkdir(exist_ok=True)

    txt_files = list(input_dir.glob("*.txt"))
    if not txt_files:
        print("在输入目录中未找到txt文件")
        return []

    print(f"找到 {len(txt_files)} 个文件")

    all_documents = []
    for txt_file in txt_files:
        print(f"正在处理: {txt_file.name}")
        with open(txt_file, 'r', encoding='utf-8') as f:
            text = f.read()

        chunks = self.split(text)
        doc_id = compute_md5(txt_file)

        for i, chunk in enumerate(chunks):
            document = Document(
                page_content=chunk,
                metadata={
                    "source": txt_file.name,
                    "chunk_id": i,
                    "doc_id": doc_id,
                }
            )
            all_documents.append(document)

    return all_documents
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_splitter_metadata.py -v`
Expected: 1 passed。

- [ ] **Step 5: Commit**

```bash
git add utils/txt_spliter/spliter.py test/test_splitter_metadata.py
git commit -m "feat(splitter): include doc_id (MD5) in chunk metadata"
```

---

## Task 4: Milvus schema 加 source/chunk_id/doc_id + 写入

**Files:**
- Modify: `utils/txt_spliter/vector_main.py:73-103`

- [ ] **Step 1: Write integration test**

修改 `test/test_vector_split.py:34-44`，扩展现有断言：

```python
# 在 line 43 之后添加：
rows = client.query(coll, output_fields=["id", "source", "chunk_id", "doc_id"], limit=10)
assert len(rows) > 0, f"期望 query 返回行，实际 {len(rows)}"
# 新增 metadata 字段断言
first_row = rows[0]
assert "source" in first_row, f"rows 缺 source 字段: {first_row.keys()}"
assert "chunk_id" in first_row, f"rows 缺 chunk_id 字段"
assert "doc_id" in first_row, f"rows 缺 doc_id 字段"
assert isinstance(first_row["chunk_id"], int)
assert len(first_row["doc_id"]) == 32, f"doc_id 应为 32 字符 MD5 hex, 实际 {first_row['doc_id']}"
assert len(first_row["source"]) > 0
print(f"[PASS] alias 指向 {coll}, query 返回 {len(rows)} 行, metadata 字段完整")
```

- [ ] **Step 2: Run test to verify it fails**

前置：Milvus + Ollama 运行中。

Run: `python test/test_vector_split.py`
Expected: AssertionError on `'source' in first_row` → FAIL。

- [ ] **Step 3: Modify vector_main.py schema**

`utils/txt_spliter/vector_main.py:73-77`，替换 schema 定义：

```python
schema = client.create_schema(enable_dynamic_field=True)
schema.add_field(field_name='id',       datatype=DataType.INT64,        is_primary=True, auto_id=True)
schema.add_field(field_name='vector',   datatype=DataType.FLOAT_VECTOR, dim=dim)
schema.add_field(field_name='text',     datatype=DataType.VARCHAR,      max_length=65535)
schema.add_field(field_name='source',   datatype=DataType.VARCHAR,      max_length=512)
schema.add_field(field_name='chunk_id', datatype=DataType.INT64)
schema.add_field(field_name='doc_id',   datatype=DataType.VARCHAR,      max_length=64)
```

`utils/txt_spliter/vector_main.py:84-103`，替换 `all_texts` 收集与 entities 构造：

```python
all_texts = [doc.page_content for doc in documents]
all_sources = [doc.metadata.get("source", "") for doc in documents]
all_chunk_ids = [int(doc.metadata.get("chunk_id", 0)) for doc in documents]
all_doc_ids = [doc.metadata.get("doc_id", "") for doc in documents]
print(f"正在为 {len(all_texts)} 个文档片段生成 embedding...")

vectors = ollama_embed_texts(all_texts)
print(f"生成 {len(vectors)} 个向量")

batch_size = 100
total_inserted = 0

for i in range(0, len(documents), batch_size):
    batch_end = min(i + batch_size, len(documents))
    batch_vectors = vectors[i:batch_end]
    batch_texts = all_texts[i:batch_end]
    batch_sources = all_sources[i:batch_end]
    batch_chunk_ids = all_chunk_ids[i:batch_end]
    batch_doc_ids = all_doc_ids[i:batch_end]

    entities = [
        {
            'vector': batch_vectors[j],
            'text': batch_texts[j],
            'source': batch_sources[j],
            'chunk_id': batch_chunk_ids[j],
            'doc_id': batch_doc_ids[j],
        }
        for j in range(len(batch_texts))
    ]

    result = client.insert(collection_name=new_collection_name, data=entities)
    total_inserted += result['insert_count']
    print(f"已插入 {total_inserted}/{len(documents)} 个片段")
```

- [ ] **Step 4: Run integration test**

前置：Milvus + Ollama 运行中。

Run: `python test/test_vector_split.py`
Expected: 通过，含新 metadata 字段断言。

- [ ] **Step 5: Commit**

```bash
git add utils/txt_spliter/vector_main.py test/test_vector_split.py
git commit -m "feat(milvus): add source/chunk_id/doc_id fields to schema and inserts"
```

---

## Task 5: `RagModel._search_similar_chunks` 返回 `List[RetrievalHit]`（含 fallback）

**Files:**
- Modify: `core/rags/rags.py:88-127`
- Create: `test/test_rag_retrieve.py`

- [ ] **Step 1: Write the failing test**

`test/test_rag_retrieve.py`:

```python
"""test/test_rag_retrieve.py —— RagModel._search_similar_chunks 结构化返回测试（mock Milvus）。"""
from unittest.mock import MagicMock, patch

from core.rags.rags import RagModel
from core.rags.types import RetrievalHit


class _MockEntity(dict):
    def __init__(self, data):
        super().__init__(data)


class _MockHit:
    def __init__(self, entity_data, distance):
        self.entity = _MockEntity(entity_data)
        self.distance = distance


def _make_model_with_mock_client(mock_client):
    """绕过真实 RagModel.__init__，直接注入 mock Milvus 客户端。"""
    m = RagModel.__new__(RagModel)
    m._client = mock_client
    m._collection_name = "txt_data"
    m._embed = MagicMock()
    m._embed.embed_query.return_value = [0.1] * 1024
    m.model_manager = MagicMock()
    return m


def test_search_returns_retrieval_hits():
    """_search_similar_chunks 应返回 List[RetrievalHit] 含全部字段。"""
    mock_client = MagicMock()
    mock_client.search.return_value = [[
        _MockHit({"text": "hello", "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}, 0.1),
        _MockHit({"text": "world", "source": "b.md", "chunk_id": 1, "doc_id": "y" * 32}, 0.2),
    ]]
    m = _make_model_with_mock_client(mock_client)
    hits = m._search_similar_chunks("q", top_k=2)
    assert len(hits) == 2
    assert all(isinstance(h, RetrievalHit) for h in hits)
    assert hits[0].text == "hello"
    assert hits[0].source == "a.md"
    assert hits[0].chunk_id == 0
    assert hits[0].doc_id == "x" * 32
    assert hits[0].score == 0.1
    assert hits[1].score == 0.2


def test_search_falls_back_when_metadata_fields_missing():
    """旧 collection 缺 source/chunk_id/doc_id 时, hit 各字段降级为空字符串/0。"""
    mock_client = MagicMock()
    # 第一次 search 抛异常（缺字段），第二次退回只用 text
    mock_client.search.side_effect = [
        Exception("field not exists"),
        [[_MockHit({"text": "only text"}, 0.3)]],
    ]
    m = _make_model_with_mock_client(mock_client)
    hits = m._search_similar_chunks("q", top_k=1)
    assert len(hits) == 1
    assert hits[0].text == "only text"
    assert hits[0].source == ""
    assert hits[0].chunk_id == 0
    assert hits[0].doc_id == ""
    # 验证 fallback 用了 output_fields=['text']
    second_call_kwargs = mock_client.search.call_args_list[1].kwargs
    assert second_call_kwargs["output_fields"] == ["text"]


def test_search_returns_empty_when_no_client():
    """向量库未加载时返回空 list。"""
    m = RagModel.__new__(RagModel)
    m._client = None
    m._collection_name = "txt_data"
    assert m._search_similar_chunks("q") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_rag_retrieve.py -v`
Expected: TypeError（现有 `_search_similar_chunks` 返回 `List[str]`）→ FAIL。

- [ ] **Step 3: Modify rags.py**

`core/rags/rags.py`，文件顶部加 import：

```python
from core.rags.types import RetrievalHit, format_citations_footer
```

替换 `_search_similar_chunks`（88-118 行）：

```python
def _search_similar_chunks(self, query: str, top_k: int = 5) -> List[RetrievalHit]:
    """向量相似度搜索，返回 List[RetrievalHit]。

    旧 collection 缺 source/chunk_id/doc_id 字段时 fallback 到只读 text，
    缺失字段降级为 '' 或 0，并记 warning 提示需重新索引。
    """
    if not self._client:
        logger.warning("向量库未加载，无法进行相似度搜索")
        return []

    try:
        query_vector = self._embed.embed_query(query)
        results = self._client.search(
            collection_name=self._collection_name,
            data=[query_vector],
            limit=top_k,
            output_fields=['text', 'source', 'chunk_id', 'doc_id'],
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
        # Fallback：可能旧 collection 缺 metadata 字段
        logger.warning(f"检索新字段失败, fallback 到 text-only: {e}")
        try:
            query_vector = self._embed.embed_query(query)
            results = self._client.search(
                collection_name=self._collection_name,
                data=[query_vector],
                limit=top_k,
                output_fields=['text'],
            )
            return [
                RetrievalHit(
                    text=h.entity.get('text', ''),
                    source="",
                    chunk_id=0,
                    doc_id="",
                    score=float(h.distance),
                )
                for h in results[0]
            ]
        except Exception as e2:
            logger.exception(f"检索 fallback 也失败：{e2}")
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_rag_retrieve.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add core/rags/rags.py test/test_rag_retrieve.py
git commit -m "feat(rags): return List[RetrievalHit] from _search_similar_chunks with fallback"
```

---

## Task 6: `RagModel.chat()` 收集 citations + 拼接 footer

**Files:**
- Modify: `core/rags/rags.py:120-178` (`retrieve`, `_build_context_prompt`, `chat`)
- Create: `test/test_rag_chat_citations.py`

- [ ] **Step 1: Write the failing test**

`test/test_rag_chat_citations.py`:

```python
"""test/test_rag_chat_citations.py —— RagModel.chat() 收集 citations + 拼接 footer。"""
from unittest.mock import MagicMock

from core.rags.rags import RagModel
from core.rags.types import RetrievalHit


def _make_model(monkeypatch=None):
    """构造一个 RagModel，绕过 Milvus，注入 mock hits + mock LLM。"""
    m = RagModel.__new__(RagModel)
    m._client = MagicMock()
    m._collection_name = "txt_data"
    m._embed = MagicMock()
    m._embed.embed_query.return_value = [0.1] * 1024
    # 注入 2 个 mock hits
    m._search_similar_chunks = lambda query, top_k=5: [
        RetrievalHit(text="chunk-A", source="RAG.md", chunk_id=0, doc_id="a" * 32, score=0.1),
        RetrievalHit(text="chunk-B", source="简历.md", chunk_id=3, doc_id="b" * 32, score=0.2),
    ]
    # mock 当前模型
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = "我找到了相关知识。chunk-A 提到..."
    m.model_manager = MagicMock()
    m.model_manager.get_current_model.return_value = mock_llm
    # 简化 msg_manager
    m.msg_manager = MagicMock()
    m.msg_manager.ensure_session.return_value = "s1"
    m.msg_manager.build_messages.return_value = [{"role": "user", "content": "q"}]
    return m, mock_llm


def test_chat_returns_citations_and_footer():
    """chat() 返回 dict 含 response（带 footer）和 citations。"""
    m, _ = _make_model()
    result = m.chat("q")
    assert "response" in result
    assert "citations" in result
    assert len(result["citations"]) == 2
    assert result["citations"][0]["index"] == 1
    assert result["citations"][0]["source"] == "RAG.md"
    assert result["citations"][0]["chunk_id"] == 0
    assert result["citations"][1]["index"] == 2
    # response 末尾应含 footer
    assert "参考资料：" in result["response"]
    assert "[1] RAG.md（chunk 0）" in result["response"]
    assert "[2] 简历.md（chunk 3）" in result["response"]


def test_chat_no_citations_no_footer():
    """hits 为空时 response 不含 footer, citations 为空。"""
    m, _ = _make_model()
    m._search_similar_chunks = lambda query, top_k=5: []
    result = m.chat("q")
    assert result["citations"] == []
    assert "参考资料：" not in result["response"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_rag_chat_citations.py -v`
Expected: AssertionError（现有 `chat()` 返回 `{"response": str}` 不含 citations）→ FAIL。

- [ ] **Step 3: Modify rags.py retrieve / _build_context_prompt / chat**

`core/rags/rags.py`，替换 `retrieve`（120-127 行）：

```python
def retrieve(self, query: str, top_k: int = 5) -> List[RetrievalHit]:
    """公开检索入口：只返回 List[RetrievalHit]，不调 LLM。

    给 agent 当工具用：方案 2（1-LLM 路径）。
    内部可演进——未来加重排 / 混合检索时,只改这个方法体,agent 工具代码 0 改动。
    """
    return self._search_similar_chunks(query, top_k)
```

替换 `_build_context_prompt`（129-154 行），接收 hits 而非 str：

```python
def _build_context_prompt(self, query: str, hits: List[RetrievalHit]) -> str:
    """构建包含上下文的提示词（带 [N] 编号）。"""
    if not hits:
        context = "没有找到相关文档片段。"
    else:
        parts = [
            f"[{i}] 来源：{h.source}（chunk {h.chunk_id}）\n{h.text}"
            for i, h in enumerate(hits, 1)
        ]
        context = "\n\n---\n\n".join(parts)

    return f"""你是一个基于RAG的个人知识库问答助手。

身份：当被问你是谁，回答"我是RAGMI"。

规则：
- 严格基于以下文档回答
- 文档无信息则告知无法回答
- 当答案使用到文档内容时, 请在段落末尾用 [1][2] 标注对应来源编号
- 用户追问"依据"时再引用文档

文档：{context}

问题：{query}"""
```

替换 `chat`（156-178 行）：

```python
def chat(self, query: str, session_id: str = None) -> Dict[str, object]:
    """主业务：输入字符串，返回 {"response": str, "citations": [...]}。"""
    session_id = self.msg_manager.ensure_session(session_id)

    hits = self._search_similar_chunks(query, top_k=5)
    citations = [
        {"index": i + 1, "source": h.source, "chunk_id": h.chunk_id, "doc_id": h.doc_id}
        for i, h in enumerate(hits, 1)
    ]

    custom_system = self._build_context_prompt(query, hits)
    messages = self.msg_manager.build_messages(session_id, query, custom_system)
    model = self.model_manager.get_current_model()
    response = model.invoke(messages)
    self.msg_manager.add_to_history(session_id, query, response)

    final_response = response + ("\n\n" + format_citations_footer(citations) if citations else "")

    return {"response": final_response, "citations": citations}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_rag_chat_citations.py test/test_rag_retrieve.py -v`
Expected: 全部 passed。

- [ ] **Step 5: Commit**

```bash
git add core/rags/rags.py test/test_rag_chat_citations.py
git commit -m "feat(rags): chat() collects citations and appends footer"
```

---

## Task 7: `rag_search` 工具打 [N] 编号 + `_record_hits` / `consume_last_hits`

**Files:**
- Modify: `agent/tools/rag_tool.py:33-52`
- Create: `test/test_rag_tool_citations.py`

- [ ] **Step 1: Write the failing test**

`test/test_rag_tool_citations.py`:

```python
"""test/test_rag_tool_citations.py —— rag_search 工具编号化 + 状态读写测试。"""
from unittest.mock import MagicMock, patch

from core.rags.types import RetrievalHit
from agent.tools import rag_tool


def _set_last_hits(hits):
    """直接设置模块级 _LAST_HITS（绕过工具调用）。"""
    rag_tool._LAST_HITS = hits


def _read_last_hits():
    return rag_tool._LAST_HITS


def test_rag_search_numbers_hits_with_brackets():
    """rag_search 输出每条 hit 以 '[N] 来源：source（chunk N）\\ntext' 开头。"""
    fake_hits = [
        RetrievalHit(text="alpha", source="a.md", chunk_id=0, doc_id="a" * 32, score=0.1),
        RetrievalHit(text="beta", source="b.md", chunk_id=2, doc_id="b" * 32, score=0.2),
    ]
    with patch.object(rag_tool, "_ensure_rag") as mock_ensure:
        mock_rag = MagicMock()
        mock_rag.retrieve.return_value = fake_hits
        mock_ensure.return_value = mock_rag
        out = rag_tool.rag_search.invoke({"query": "q"})

    assert "[1] 来源：a.md（chunk 0）" in out
    assert "[2] 来源：b.md（chunk 2）" in out
    assert "alpha" in out
    assert "beta" in out


def test_rag_search_empty_hits_returns_message():
    """无 hits 时工具返回中文固定提示。"""
    with patch.object(rag_tool, "_ensure_rag") as mock_ensure:
        mock_rag = MagicMock()
        mock_rag.retrieve.return_value = []
        mock_ensure.return_value = mock_rag
        out = rag_tool.rag_search.invoke({"query": "q"})
    assert "没有找到" in out


def test_rag_search_records_hits_for_consume():
    """rag_search 调用后, _LAST_HITS 已被填充。"""
    fake_hits = [
        RetrievalHit(text="x", source="x.md", chunk_id=0, doc_id="x" * 32, score=0.1),
    ]
    _set_last_hits([])  # 清空
    with patch.object(rag_tool, "_ensure_rag") as mock_ensure:
        mock_rag = MagicMock()
        mock_rag.retrieve.return_value = fake_hits
        mock_ensure.return_value = mock_rag
        rag_tool.rag_search.invoke({"query": "q"})
    assert len(_read_last_hits()) == 1


def test_consume_last_hits_returns_indexed_dicts_and_clears():
    """consume_last_hits 返回 [{index, source, chunk_id, doc_id}, ...] 并清空 _LAST_HITS。"""
    _set_last_hits([
        RetrievalHit(text="x", source="x.md", chunk_id=0, doc_id="x" * 32, score=0.1),
        RetrievalHit(text="y", source="y.md", chunk_id=2, doc_id="y" * 32, score=0.2),
    ])
    out = rag_tool.consume_last_hits()
    assert out == [
        {"index": 1, "source": "x.md", "chunk_id": 0, "doc_id": "x" * 32},
        {"index": 2, "source": "y.md", "chunk_id": 2, "doc_id": "y" * 32},
    ]
    assert _read_last_hits() == []  # 已清空


def test_consume_last_hits_when_empty():
    """_LAST_HITS 为空时, consume 返回空 list。"""
    _set_last_hits([])
    assert rag_tool.consume_last_hits() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_rag_tool_citations.py -v`
Expected: AttributeError（`rag_tool` 没有 `_LAST_HITS` / `consume_last_hits`）→ FAIL。

- [ ] **Step 3: Modify rag_tool.py**

`agent/tools/rag_tool.py` 全文替换为：

```python
"""agent/tools/rag_tool.py —— RAGMI 知识库检索工具（方案 2：1-LLM 路径）。

设计选择：
1. 只检索、不生成 —— 工具返回带 [N] 编号的 chunks，最终答案由 agent LLM 自己综合
2. 走 RagModel.retrieve() 公开方法 —— 不穿透私有方法，未来 RAG 演进不影响 agent
3. 懒加载 RagModel 单例 —— 首次调用才连 Milvus，后续复用
4. 显式用 MiniMax-M3 —— 构造 RagModel 时指定（虽然方案 2 不用 RAG 内部 LLM，
   但 RagModel.__init__ 要求 model_manager，所以配一个真实的）

结构化 citations 传递：
- 工具返回 string（langchain @tool 契约）
- 结构化 hits 暂存到模块级 _LAST_HITS
- agent_node 调用 consume_last_hits() 读 + 清空
"""
from langchain_core.tools import tool

from core.rags.rags import RagModel
from core.rags.types import RetrievalHit
from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel


_rag_model: RagModel | None = None

# 模块级状态：最近一次 rag_search 的结构化 hits（agent_node 读后清空）
_LAST_HITS: list[RetrievalHit] = []


def _ensure_rag() -> RagModel:
    """懒加载 RAG 单例。首次调用连接 Milvus + 初始化 embedding。"""
    global _rag_model
    if _rag_model is None:
        manager = ModelManager()
        manager.load_config_models()
        rag_llm = LLMmodel.create_minimax("MiniMax-M3")
        manager.set_current_model(rag_llm)
        _rag_model = RagModel(manager)
    return _rag_model


def _record_hits(hits: list[RetrievalHit]) -> None:
    """记录本次 rag_search 的结构化 hits。"""
    global _LAST_HITS
    _LAST_HITS = list(hits)


def consume_last_hits() -> list[dict]:
    """读 + 清空 _LAST_HITS，返回 index/source/chunk_id/doc_id 字典列表。

    由 agent_node 在 LLM 返回答案后调用，把结构化 citations 写回 state。
    """
    global _LAST_HITS
    out = [
        {
            "index": i + 1,
            "source": h.source,
            "chunk_id": h.chunk_id,
            "doc_id": h.doc_id,
        }
        for i, h in enumerate(_LAST_HITS, 1)
    ]
    _LAST_HITS = []
    return out


@tool
def rag_search(query: str) -> str:
    """从 RAGMI 个人知识库检索与 query 相关的内容片段。

    适用：
    - "我的 X" / "我最近的 X" / "你了解我..." 等个人上下文
    - 涉及用户上传过的文档 / 笔记 / 资料

    不适用：
    - 通用概念 / 原理（如"什么是 X 模式"）
    - 闲聊 / 问候

    返回：检索到的文档片段，每个片段以 [N] 来源：filename（chunk M） 开头，
    多个片段用 --- 分隔。工具不做最终综合，由 agent 基于这些片段自行作答。
    """
    model = _ensure_rag()
    hits = model.retrieve(query, top_k=5)
    _record_hits(hits)
    if not hits:
        return "（知识库中没有找到相关文档）"
    parts = [f"[{i}] 来源：{h.source}（chunk {h.chunk_id}）\n{h.text}"
             for i, h in enumerate(hits, 1)]
    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_rag_tool_citations.py -v`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add agent/tools/rag_tool.py test/test_rag_tool_citations.py
git commit -m "feat(agent-tool): rag_search numbers hits + record/consume state"
```

---

## Task 8: `AgentState.citations` + `agent_node` 写回 citations

**Files:**
- Modify: `agent/state.py:27-54`
- Modify: `agent/nodes/agent.py:37-56`
- Create: `test/test_agent_node_citations.py`

- [ ] **Step 1: Write the failing test**

`test/test_agent_node_citations.py`:

```python
"""test/test_agent_node_citations.py —— agent_node 写回 state.citations。"""
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

from agent.nodes import agent as agent_mod
from core.rags.types import RetrievalHit


def _make_state_with_messages():
    return {"messages": []}


def test_agent_node_writes_citations_from_last_hits():
    """agent_node 返回值含 citations 字段, 来自 consume_last_hits()。"""
    fake_hits = [
        RetrievalHit(text="x", source="x.md", chunk_id=0, doc_id="x" * 32, score=0.1),
        RetrievalHit(text="y", source="y.md", chunk_id=2, doc_id="y" * 32, score=0.2),
    ]
    # 预填 _LAST_HITS
    from agent.tools import rag_tool
    rag_tool._LAST_HITS = fake_hits

    # mock LLM
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content="answer")
    with patch.object(agent_mod, "_get_llm", return_value=mock_llm):
        result = agent_mod.agent_node(_make_state_with_messages())

    assert "citations" in result
    assert result["citations"] == [
        {"index": 1, "source": "x.md", "chunk_id": 0, "doc_id": "x" * 32},
        {"index": 2, "source": "y.md", "chunk_id": 2, "doc_id": "y" * 32},
    ]
    assert result["iterations"] == 1
    # _LAST_HITS 应已被 consume 清空
    assert rag_tool._LAST_HITS == []


def test_agent_node_no_citations_when_no_hits():
    """无 _LAST_HITS 时, citations 字段为空 list。"""
    from agent.tools import rag_tool
    rag_tool._LAST_HITS = []

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content="chat answer")
    with patch.object(agent_mod, "_get_llm", return_value=mock_llm):
        result = agent_mod.agent_node(_make_state_with_messages())

    assert result["citations"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_agent_node_citations.py -v`
Expected: KeyError 'citations' / AssertionError → FAIL。

- [ ] **Step 3: Modify state.py**

`agent/state.py:27-54`，在 class 末尾加字段：

```python
class AgentState(TypedDict, total=False):
    """Agent 运行时状态。

    total=False 表示：所有字段都可选，新建会话可直接传入空 dict 起步。

    字段说明
    --------
    messages : list[BaseMessage]
        消息历史（用户 / AI / 工具三类轮流出现）。
        add_messages 是 LangGraph 的 reducer：每个节点 return {"messages": [...]} 时，
        引擎调用 add_messages 决定如何合并到现有 messages。

    iterations : int
        agent 节点执行次数计数器。超 MAX_ITERS 强制 END（should_continue 里检查）。

    reflection_count : int
        reflect_node 执行次数计数器。超 MAX_REFL 强制 pass（reflect_node 里检查）。

    last_reflection_pass : bool
        最近一次 reflect_node 评判结果。条件边 after_reflect 读这个决定路由。
        - True → END（通过）
        - False → agent（带 critique 重答）

    citations : list[dict]  ← v2.2 新增（spec: metadata + 引用）
        最近一次 rag_search 的结构化 citations（index/source/chunk_id/doc_id）。
        agent_node 在 LLM 返回答案后写入。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    iterations: Annotated[int, _increment]
    reflection_count: Annotated[int, _increment]
    last_reflection_pass: bool
    citations: list[dict]
```

- [ ] **Step 4: Modify agent.py**

`agent/nodes/agent.py:37-56`，替换 `agent_node`：

```python
def agent_node(state: dict) -> dict:
    """Agent 决策节点。

    输入：state dict（含 messages）
    输出：{"messages": [AIMessage], "iterations": 1, "citations": [...]}
         - citations 来自最近一次 rag_search（由 rag_tool.consume_last_hits() 提供）
    """
    from agent.tools import rag_tool

    llm = _get_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
    response = llm.invoke(messages)

    citations = rag_tool.consume_last_hits()

    return {"messages": [response], "iterations": 1, "citations": citations}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest test/test_agent_node_citations.py -v`
Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
git add agent/state.py agent/nodes/agent.py test/test_agent_node_citations.py
git commit -m "feat(agent): collect citations from last rag_search into state"
```

---

## Task 9: `system_prompt.py` 增加引用规则

**Files:**
- Modify: `agent/prompts/system_prompt.py:8-26`

- [ ] **Step 1: Write the failing test**

`test/test_system_prompt.py`（新文件）:

```python
"""test/test_system_prompt.py —— SYSTEM_PROMPT 含引用规则关键字。"""
from agent.prompts.system_prompt import SYSTEM_PROMPT


def test_system_prompt_mentions_citation_rule():
    """SYSTEM_PROMPT 应包含引用规则的标识字符串。"""
    assert "引用规则" in SYSTEM_PROMPT
    assert "[1]" in SYSTEM_PROMPT
    assert "[2]" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_system_prompt.py -v`
Expected: AssertionError '引用规则' not in → FAIL。

- [ ] **Step 3: Modify system_prompt.py**

`agent/prompts/system_prompt.py:8-26`，替换 `SYSTEM_PROMPT` 字符串：

```python
SYSTEM_PROMPT = """你是 RAGMI 智能助手。仅可调用 1 个工具：rag_search(query)。

【何时调 rag_search】
- "我的 X" / "我最近的 X" / "你了解我..." → 个人上下文
- 涉及用户上传的文档、笔记、资料

【何时不调（直接答）】
- 通用概念 / 原理 / 知识（如"什么是 X 模式"）
- 闲聊 / 问候

【当工具返回文档片段时】
- 必须严格基于这些片段作答
- 片段无信息则坦白说不知道，不可用通用知识补
- 可综合多片段，但不要超出片段范围

【引用规则】
- 当基于检索片段回答时，请在段落末尾或文末用 [1][2][3] 标注来源编号
- 编号必须与检索片段前的 [N] 一致
- 若未检索到任何片段，则不写引用

【输出规则】
- 中文、自然
- 不瞎编
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_system_prompt.py -v`
Expected: 1 passed。

- [ ] **Step 5: Commit**

```bash
git add agent/prompts/system_prompt.py test/test_system_prompt.py
git commit -m "feat(agent-prompt): add citation rules to SYSTEM_PROMPT"
```

---

## Task 10: `runtime.ask()` 返回 dict 含 citations

**Files:**
- Modify: `agent/runtime.py:53-99`

- [ ] **Step 1: Write the failing test**

`test/test_runtime_citations.py`（新文件）:

```python
"""test/test_runtime_citations.py —— runtime.ask() 返回 dict 含 citations。"""
from unittest.mock import MagicMock, patch


def test_ask_returns_dict_with_response_and_citations_when_no_debug():
    """ask(debug=False) 返回 dict 含 response 和 citations, 不含 iterations/score。"""
    with patch("agent.runtime._get_graph") as mock_get_graph:
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "messages": [MagicMock(content="answer text")],
            "iterations": 2,
            "reflection_count": 1,
            "last_reflection_pass": True,
            "citations": [
                {"index": 1, "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}
            ],
        }
        mock_get_graph.return_value = mock_graph

        from agent.runtime import ask
        result = ask("q")

    assert isinstance(result, dict)
    assert "response" in result
    assert "citations" in result
    assert result["response"] == "answer text"
    assert len(result["citations"]) == 1
    assert "iterations" not in result  # debug=False 不返回


def test_ask_appends_citations_footer_when_no_debug():
    """ask(debug=False) 在 response 末尾追加参考资料行。"""
    with patch("agent.runtime._get_graph") as mock_get_graph:
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "messages": [MagicMock(content="answer text")],
            "citations": [
                {"index": 1, "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}
            ],
        }
        mock_get_graph.return_value = mock_graph

        from agent.runtime import ask
        result = ask("q")

    assert "参考资料：" in result["response"]
    assert "[1] a.md（chunk 0）" in result["response"]


def test_ask_debug_includes_citations_and_metadata():
    """ask(debug=True) 返回完整 metadata + citations。"""
    with patch("agent.runtime._get_graph") as mock_get_graph:
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "messages": [MagicMock(content="ans")],
            "iterations": 1,
            "reflection_count": 0,
            "last_reflection_pass": False,
            "citations": [{"index": 1, "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}],
        }
        mock_get_graph.return_value = mock_graph

        from agent.runtime import ask
        result = ask("q", debug=True)

    assert result["citations"] == [{"index": 1, "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}]
    assert result["iterations"] == 1
    assert "answer" in result  # debug 用 answer 字段


def test_ask_returns_error_dict_on_exception():
    """graph.invoke 抛异常时, ask 返回错误 dict 不抛。"""
    with patch("agent.runtime._get_graph") as mock_get_graph:
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = RuntimeError("boom")
        mock_get_graph.return_value = mock_graph

        from agent.runtime import ask
        result = ask("q")

    assert isinstance(result, dict)
    assert result["response"].startswith("抱歉")
    assert result["citations"] == []
    assert result.get("error") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_runtime_citations.py -v`
Expected: AssertionError（`ask` 当前返回 str）→ FAIL。

- [ ] **Step 3: Modify runtime.py**

`agent/runtime.py`，全文替换为：

```python
"""agent/runtime.py —— 对外统一调用入口 (v2.2 spec: metadata + 引用)。

v2.1 增强：
- 异常统一兜底（LLM 调用失败 / 超时不会 500）
- debug 模式返回 metadata（iterations / reflection_count / score / tool_called）

v2.2 增强：
- 返回值统一为 dict：{response, citations}
- response 末尾追加参考资料 footer（强制）
- debug 模式额外含 iterations / reflection_count / score / tool_called
"""
from agent.graph import build_graph
from core.rags.types import format_citations_footer
from utils.logging import get_logger

logger = get_logger(__name__)


_graph = None


def _get_graph():
    """懒加载 graph 单例。"""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _compute_score(result: dict):
    refl_count = result.get("reflection_count", 0)
    if refl_count == 0:
        return None
    return bool(result.get("last_reflection_pass", False))


def _error_response_dict(debug: bool) -> dict:
    msg = "抱歉，agent 调用异常，请稍后重试。"
    base = {"response": msg, "citations": [], "error": True}
    if debug:
        base.update({"answer": msg, "iterations": 0, "reflection_count": 0, "score": None, "tool_called": False})
    return base


def ask(
    question: str,
    session_id: str | None = None,
    debug: bool = False,
) -> dict:
    """统一对话入口。

    输入：
    - question: 用户问题
    - session_id: 会话 ID（暂未启用多轮持久化）
    - debug: 是否返回完整 metadata

    输出：dict 总是返回
    - debug=False: {"response": str（含 footer）, "citations": [...]}
    - debug=True:  {answer, response（含 footer）, citations, iterations, reflection_count, score, tool_called}
    """
    graph = _get_graph()
    config = {"configurable": {"thread_id": session_id}} if session_id else None

    logger.info(f"ask() entry: query={question[:50]}... session={session_id}")

    try:
        result = graph.invoke(
            {"messages": [("user", question)]},
            config=config,
        )
    except Exception as e:
        logger.exception(f"ask() failed: {type(e).__name__}: {e}")
        return _error_response_dict(debug)

    answer = result["messages"][-1].content
    citations = result.get("citations") or []

    footer = format_citations_footer(citations) if citations else ""
    final_answer = answer + ("\n\n" + footer if footer else "")

    if not debug:
        return {"response": final_answer, "citations": citations}

    tool_called = any(
        msg.__class__.__name__ == "ToolMessage"
        for msg in result["messages"]
    )
    return {
        "answer": final_answer,
        "response": final_answer,
        "citations": citations,
        "iterations": result.get("iterations", 0),
        "reflection_count": result.get("reflection_count", 0),
        "score": _compute_score(result),
        "tool_called": tool_called,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_runtime_citations.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add agent/runtime.py test/test_runtime_citations.py
git commit -m "feat(agent-runtime): ask() returns dict with response and citations"
```

---

## Task 11: API 层响应契约更新

**Files:**
- Modify: `api/api_rag.py`
- Modify: `api/api_agent.py`
- Create: `test/test_api_responses.py`

- [ ] **Step 1: Read existing api_rag.py and api_agent.py to plan minimal edits**

Read:
- `api/api_rag.py`（找当前路由函数 return 形式）
- `api/api_agent.py`（找当前 `ask()` 调用与 return 形式）

- [ ] **Step 2: Write the failing test**

`test/test_api_responses.py`:

```python
"""test/test_api_responses.py —— /rag 与 /agent/chat 响应契约含 citations。"""
from unittest.mock import MagicMock, patch


def test_rag_response_has_response_and_citations():
    """/rag 返回 dict 含 response 和 citations。"""
    from fastapi.testclient import TestClient
    from api.api_rag import app

    client = TestClient(app)
    mock_result = {"response": "answer text", "citations": [{"index": 1, "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}]}

    with patch("api.api_rag.RagModel") as MockModel:
        instance = MagicMock()
        instance.chat.return_value = mock_result
        MockModel.return_value = instance
        resp = client.post("/rag", json={"query": "q", "session_id": None})
    assert resp.status_code == 200
    body = resp.json()
    assert "response" in body
    assert "citations" in body
    assert body["citations"] == mock_result["citations"]


def test_agent_chat_response_has_response_and_citations():
    """/agent/chat 返回 dict 含 response 和 citations。"""
    from fastapi.testclient import TestClient
    from api.api_agent import app

    client = TestClient(app)
    mock_result = {"response": "answer", "citations": [{"index": 1, "source": "a.md", "chunk_id": 0, "doc_id": "x" * 32}]}

    with patch("api.api_agent.ask", return_value=mock_result):
        resp = client.post("/agent/chat", json={"question": "q"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "answer"
    assert body["citations"] == mock_result["citations"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest test/test_api_responses.py -v`
Expected: 路由响应缺 `citations` 字段或 ImportError（路径未挂载）→ FAIL。

- [ ] **Step 4: Modify api_rag.py**

在路由函数返回处（具体行号依赖 Step 1 读取结果），把：

```python
return {"response": result["response"]}
```

改为：

```python
return {"response": result["response"], "citations": result.get("citations", [])}
```

> 若现有 `RagModel.chat()` 调用形式不同（例如同步入参名不同），按现有形式调整 test 和实际调用。确保路由层读取 `result["citations"]` 字段。

- [ ] **Step 5: Modify api_agent.py**

在 `ask()` 调用点（具体行号依赖 Step 1 读取结果），把现有 str 读取改为 dict 读取：

```python
result = ask(question, session_id=session_id)
if isinstance(result, dict):
    return {"response": result.get("response", ""), "citations": result.get("citations", [])}
# 兜底：若 result 不是 dict（旧调用方残留）, 包装成 dict
return {"response": str(result), "citations": []}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest test/test_api_responses.py -v`
Expected: 2 passed。

- [ ] **Step 7: Commit**

```bash
git add api/api_rag.py api/api_agent.py test/test_api_responses.py
git commit -m "feat(api): /rag and /agent/chat return {response, citations}"
```

---

## Task 12: 跑全量回归 + 集成测试

**Files:** 不修改，只验证

- [ ] **Step 1: 跑现有单元测试**

Run: `pytest test/test_reflect.py test/test_main_routes_covered.py test/test_retrieval_hit.py test/test_doc_id.py test/test_splitter_metadata.py test/test_rag_retrieve.py test/test_rag_chat_citations.py test/test_rag_tool_citations.py test/test_agent_node_citations.py test/test_system_prompt.py test/test_runtime_citations.py test/test_api_responses.py -v`

Expected: 全部 passed。

- [ ] **Step 2: 跑 Milvus 集成测试**

前置：Milvus + Ollama 运行中；`txt/` 至少有一个文件。

Run: `python test/test_vector_split.py`
Expected: `[PASS] alias 指向 txt_data_<ts>, query 返回 N 行, metadata 字段完整`。

- [ ] **Step 3: 跑 Agent mock 评估**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py --mock`

Expected: 12 个 case，routing accuracy ≥ 90%，stability = 100%。

- [ ] **Step 4: 启动后端做手动端到端冒烟**

Run: `python main.py` （另一个终端）
- `curl http://localhost:8000/rag` 用真实 query 提交，期望响应含 `citations` 字段。
- `curl http://localhost:8000/agent/chat` 用真实 query 提交，期望响应含 `citations` 字段。

- [ ] **Step 5: Commit any final fixes**

如有任何小修正（注释、错误信息文案等），单独提交：

```bash
git commit -am "chore: post-integration cleanup"
```

---

## Self-Review

**Spec coverage check:**
- 3.1 Milvus schema + 写入 → Task 4 ✓
- 3.2 Splitter doc_id → Task 3 ✓
- 3.3 RetrievalHit + _search_similar_chunks → Task 2 + 5 ✓
- 3.4 rag_search tool → Task 7 ✓
- 3.5 system_prompt → Task 9 ✓
- 3.6 AgentState.citations → Task 8 ✓
- 3.7 agent_node collect citations → Task 8 ✓
- 3.8 /rag response → Task 11 ✓
- 3.9 /agent/chat response → Task 11 ✓
- 3.10 runtime.ask dict → Task 10 ✓
- 错误处理 (Section 5) → Task 5 (fallback) + Task 10 (error dict) ✓
- 测试策略 (Section 6) → Task 1-11 各自的 test 文件 + Task 12 集成验证 ✓

**Placeholder scan:** 无 TBD / "类似 Task N" 引用 / "实现类似代码" 漏洞。

**Type consistency:**
- `RetrievalHit(text, source, chunk_id, doc_id, score)` — 在 Task 2 定义, Task 5/6/7/8 一致使用。
- `format_citations_footer(citations)` — Task 2 定义, Task 6/10 一致调用。
- `consume_last_hits() -> list[dict]` 返回 `{index, source, chunk_id, doc_id}` — Task 7 定义, Task 8 一致消费。
- `AgentState.citations: list[dict]` — Task 8 定义, Task 10 一致读取 (`result.get("citations")`)。
- `runtime.ask()` 返回 `dict` — Task 10 定义, Task 11 一致消费 (`result["response"]` / `result["citations"]`)。

无签名不一致问题。
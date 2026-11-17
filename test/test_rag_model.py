"""test/test_rag_model.py —— L2 · RAG 检索层的失败语义（永远跑）。

测 `core/rags/rags.py` 最重要的一条契约：

    **「检索失败」和「检索到 0 条」必须可区分。**

修之前 `_search_similar_chunks` 的 `except Exception: return []`
把两者都变成空列表 —— 工具层只能记 `status="empty"`，
Agent 于是分不清「知识库里没有这条」和「知识库挂了」，
会拿着空素材硬答（P2-7）。

不连 Milvus、不调真 LLM：向量库和 LLM 都是假件。
"""
import pytest

from core.rags.rags import RagModel, RetrievalError


class FakeEmbed:
    """假的 embedding 客户端。"""

    def __init__(self, error=None):
        self.error = error

    def embed_query(self, query):
        if self.error is not None:
            raise self.error
        return [0.0] * 1024


class FakeHit:
    def __init__(self, text):
        self.entity = {"text": text}


class FakeMilvusClient:
    """假的 Milvus 客户端。"""

    def __init__(self, hits=None, error=None):
        self.hits = hits if hits is not None else []
        self.error = error
        self.calls: list[str] = []

    def search(self, collection_name, data, limit, output_fields):
        self.calls.append(collection_name)
        if self.error is not None:
            raise self.error
        return [[FakeHit(text) for text in self.hits[:limit]]]


class FakeLLM:
    """假的对话模型（RagModel.chat 用它出答案）。"""

    def __init__(self):
        self.prompts: list = []

    def invoke(self, messages):
        self.prompts.append(messages)
        return "假答案"


class FakeModelManager:
    def __init__(self):
        self.llm = FakeLLM()

    def get_current_model(self):
        return self.llm


def _make_rag_model(monkeypatch, client=None, embed=None):
    """造一个 RagModel，但**不连真 Milvus**。

    用 patch 掉 `_load_vector_store` 的方式：__init__ 的其余逻辑（字段初始化）
    仍然是真代码。
    """
    monkeypatch.setattr(RagModel, "_load_vector_store", lambda self: None)

    model = RagModel(FakeModelManager())
    model._client = client
    model._embed = embed if embed is not None else FakeEmbed()
    model._collection_name = "txt_data"
    return model


class TestRetrievalFailureIsDistinguishable:
    """失败 → 抛 RetrievalError；为空 → 返回 []。"""

    def test_store_not_loaded_raises_retrieval_error(self, monkeypatch):
        """Milvus 没连上 → RetrievalError（不是"检索为空"）。"""
        model = _make_rag_model(monkeypatch, client=None)

        with pytest.raises(RetrievalError) as excinfo:
            model.retrieve("q")

        assert "向量库未加载" in str(excinfo.value)

    def test_search_failure_raises_retrieval_error_with_cause(self, monkeypatch):
        """查询报错 → RetrievalError，且**保留原始异常**（`__cause__`）。

        工具层靠 `__cause__` 判断这是不是超时（→ 可重试）。
        """
        model = _make_rag_model(
            monkeypatch,
            client=FakeMilvusClient(error=RuntimeError("collection not found")),
        )

        with pytest.raises(RetrievalError) as excinfo:
            model.retrieve("q")

        assert "collection not found" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, RuntimeError)

    def test_embedding_failure_raises_retrieval_error(self, monkeypatch):
        """embedding 客户端报错（超时等）→ 也是 RetrievalError。"""
        model = _make_rag_model(
            monkeypatch,
            client=FakeMilvusClient(),
            embed=FakeEmbed(error=TimeoutError("read timed out")),
        )

        with pytest.raises(RetrievalError):
            model.retrieve("q")

    def test_empty_result_is_not_an_error(self, monkeypatch):
        """检索到 0 条 → 返回 []，**不抛异常**。

        这是"为空"那条路 —— 它必须和上面三条区分开。
        """
        model = _make_rag_model(monkeypatch, client=FakeMilvusClient(hits=[]))

        assert model.retrieve("q") == []

    def test_hits_are_returned_as_text(self, monkeypatch):
        """正常路径 → 返回 chunk 文本列表。"""
        model = _make_rag_model(
            monkeypatch, client=FakeMilvusClient(hits=["片段A", "片段B"])
        )

        assert model.retrieve("q") == ["片段A", "片段B"]


class TestChatStaysResilient:
    """`/rag` 直连链路：检索失败也必须返回 200（不抛）。"""

    def test_chat_returns_response_when_retrieval_fails(self, monkeypatch):
        """检索挂了 → 仍然返回 {"response": ...}，按"没有相关文档"处理。"""
        model = _make_rag_model(monkeypatch, client=None)

        result = model.chat("问题", session_id="pytest-rag-failure")

        assert "response" in result
        assert isinstance(result["response"], str)

    def test_chat_passes_no_context_when_retrieval_fails(self, monkeypatch):
        """检索失败时给模型的上下文是「没有找到相关文档片段」。"""
        model = _make_rag_model(monkeypatch, client=None)

        model.chat("问题", session_id="pytest-rag-failure-2")

        prompt = str(model.model_manager.get_current_model().prompts[0][0].content)
        assert "没有找到相关文档片段" in prompt

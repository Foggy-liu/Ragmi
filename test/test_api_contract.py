"""test/test_api_contract.py —— L3 API 契约 + 上传校验。

零外部依赖：TestClient + dependency_overrides，不连 Milvus、不调真 LLM。

⚠️ `from main import app` 必须在**模块顶层**（collection 期）：
main.py:63 在模块级调 LLMmodel.create_minimax()，若在 patch 之后才 import，
假件会变成进程默认模型 → /chat /rag 变成"对着假件测假件"。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

# ⚠️ 顶层 import —— 见本文件 docstring
from main import app

import api.api_agent as api_agent
import api.api_rag as api_rag
import api.api_file as api_file
from api.dependencies import get_chat_model


@pytest.fixture
def client():
    """FastAPI TestClient。

    ⚠️ 必须用 `with` —— 否则 lifespan 不跑，app.state.model_manager 不存在，
    /chat /rag 的依赖注入会失败。
    """
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def stub_agent(monkeypatch):
    """把 /agent/chat 的 ask 换成固定答案（不打真 LLM）。"""
    monkeypatch.setattr(api_agent, "ask", lambda query, session_id=None: "AGENT 假答案")
    return "AGENT 假答案"


@pytest.fixture
def stub_models():
    """把 /rag 和 /chat 的依赖换成假模型（不连 Milvus、不调真 LLM）。"""

    class FakeRagModel:
        def chat(self, query, session_id):
            return {"response": "RAG 假答案"}

    class FakeChatModel:
        def chat(self, query, session_id):
            return {"response": "CHAT 假答案"}

    app.dependency_overrides[api_rag.get_rag_model] = lambda: FakeRagModel()
    app.dependency_overrides[get_chat_model] = lambda: FakeChatModel()
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def stub_parser(monkeypatch):
    """把 txt_main 换成桩 —— 否则每次上传都会全量扫 documents/ 并解析（慢 + 污染）。"""
    monkeypatch.setattr(api_file, "txt_parse_main", lambda: {"note": "stubbed"})


@pytest.fixture
def restore_model(client):
    """switch_model 改的是**进程全局**模型 —— 测完必须还原。"""
    before = client.get("/current_model").json()
    try:
        yield before
    finally:
        client.post("/switch_model", json=before)


# ---------------------------------------------------------------------------
# C1–C7 · 契约
# ---------------------------------------------------------------------------

def test_c1_agent_chat_returns_response_key(client, stub_agent):
    """/agent/chat 返回 200，body 恰好含 response（不含 answer）。"""
    resp = client.post("/agent/chat", json={"query": "你好"})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"response": "AGENT 假答案"}
    assert "answer" not in body


def test_c2_rag_returns_response_key(client, stub_models):
    """/rag 返回 200，body 含 response。"""
    resp = client.post("/rag", json={"query": "你好"})

    assert resp.status_code == 200
    assert resp.json() == {"response": "RAG 假答案"}


def test_c3_chat_returns_response_key(client, stub_models):
    """/chat 返回 200，body 含 response。"""
    resp = client.post("/chat", json={"query": "你好"})

    assert resp.status_code == 200
    assert resp.json() == {"response": "CHAT 假答案"}


def test_c4_missing_query_is_422_but_empty_query_is_200(client, stub_agent):
    """缺 query 字段 → 422；空串 query → **200**。

    ⚠️ api_agent.py:18 的 Field(...) 没有 min_length —— 空串不是 422。
    """
    missing = client.post("/agent/chat", json={})
    assert missing.status_code == 422

    empty = client.post("/agent/chat", json={"query": ""})
    assert empty.status_code == 200


def test_c5_debug_simple(client):
    """/debug/simple → 200，且能看到 model_manager。"""
    resp = client.get("/debug/simple")

    assert resp.status_code == 200
    assert resp.json()["是否有model_manager"] is True


def test_c6_available_models_contains_minimax(client):
    """/available → 200，列表含 minimax/MiniMax-M3.1-Flash（实测共 11 个模型）。"""
    resp = client.get("/available")

    assert resp.status_code == 200
    models = resp.json()["available_models"]
    assert {"platform": "minimax", "model_name": "MiniMax-M3.1-Flash"} in models


def test_c7_switch_model_success_and_failure(client, restore_model):
    """/switch_model 成功与失败两种响应；测完模型被还原。"""
    ok = client.post(
        "/switch_model",
        json={"platform": "minimax", "model_name": "MiniMax-M3.1-Flash"},
    )
    assert ok.status_code == 200
    assert ok.json()["success"] is True
    assert ok.json()["current_model"] == {
        "platform": "minimax", "model_name": "MiniMax-M3.1-Flash",
    }

    bad = client.post(
        "/switch_model",
        json={"platform": "minimax", "model_name": "不存在的模型"},
    )
    assert bad.status_code == 200
    assert bad.json() == {"success": False, "message": "模型切换失败"}


# ---------------------------------------------------------------------------
# C8–C10 · 上传校验（后端纯逻辑，零外部依赖）
# ---------------------------------------------------------------------------

def test_c8_path_traversal_is_rejected(client, stub_parser):
    """路径穿越 → 落进 failed_uploads，documents/ 外不产生文件。"""
    resp = client.post(
        "/api/batch-upload-and-parse",
        files=[("files", ("../../evil.txt", b"pwned", "text/plain"))],
    )

    assert resp.status_code == 200
    details = resp.json()["upload_details"]
    assert len(details["failed_uploads"]) == 1
    assert details["failed_uploads"][0]["filename"] == "../../evil.txt"
    assert "非法路径" in details["failed_uploads"][0]["reason"]
    assert details["uploaded_files"] == []
    # documents/ 外没有产生文件
    assert not list(Path("documents").glob("*evil*"))
    assert not list(Path(".").glob("*evil*"))


def test_c9_unsupported_file_type_is_rejected(client, stub_parser):
    """类型白名单 → .exe 落进 failed_uploads。"""
    resp = client.post(
        "/api/batch-upload-and-parse",
        files=[("files", ("bad.exe", b"MZ", "application/octet-stream"))],
    )

    assert resp.status_code == 200
    details = resp.json()["upload_details"]
    assert len(details["failed_uploads"]) == 1
    assert details["failed_uploads"][0]["filename"] == "bad.exe"
    assert "不支持的文件类型" in details["failed_uploads"][0]["reason"]
    assert details["uploaded_files"] == []
    assert not (Path("documents") / "bad.exe").exists()


def test_c10_same_name_is_skipped_unless_overwrite(client, stub_parser):
    """同名文件：默认跳过；overwrite=true 时覆盖。"""
    name = "pytest_probe_upload.txt"
    doc = Path("documents") / name
    if doc.exists():
        doc.unlink()

    try:
        first = client.post(
            "/api/batch-upload-and-parse",
            files=[("files", (name, b"v1", "text/plain"))],
        )
        uploaded = first.json()["upload_details"]["uploaded_files"]
        assert len(uploaded) == 1
        assert uploaded[0]["filename"] == name
        assert uploaded[0]["status"] == "新增"

        second = client.post(
            "/api/batch-upload-and-parse",
            files=[("files", (name, b"v2", "text/plain"))],
        )
        details = second.json()["upload_details"]
        assert details["uploaded_files"] == []
        assert len(details["skipped_files"]) == 1
        assert details["skipped_files"][0]["filename"] == name

        third = client.post(
            "/api/batch-upload-and-parse",
            files=[("files", (name, b"v3", "text/plain"))],
            params={"overwrite": "true"},
        )
        uploaded = third.json()["upload_details"]["uploaded_files"]
        assert len(uploaded) == 1
        assert uploaded[0]["status"] == "覆盖"
    finally:
        if doc.exists():
            doc.unlink()


# ---------------------------------------------------------------------------
# C11 · 依赖注入：RagModel 单例（P1-4）
# ---------------------------------------------------------------------------

class TestRagModelSingleton:
    """`/rag` 的 RagModel 必须是 **app 级单例**（P1-4）。

    FastAPI 的 `Depends` 缓存只在**单个请求内**有效，跨请求不复用；
    而 `RagModel.__init__` 要新建一条 Milvus gRPC 连接（实测 ~0.9 秒）。
    每个请求现建 = 每个请求都开一条连接、用一次就扔掉。
    """

    @staticmethod
    def _request(state):
        """造一个只有 `.app.state` 的假 Request。"""
        return SimpleNamespace(app=SimpleNamespace(state=state))

    def test_second_call_reuses_the_same_instance(self, monkeypatch):
        """第二次拿到的必须是同一个对象，且只构造过一次。"""
        import api.dependencies as deps

        built = []

        class FakeRag:
            def __init__(self, model_manager):
                built.append(model_manager)
                self.is_ready = True

        monkeypatch.setattr(deps, "RagModel", FakeRag)
        state = SimpleNamespace(model_manager="MGR")

        first = deps.get_rag_model(self._request(state))
        second = deps.get_rag_model(self._request(state))

        assert first is second
        assert len(built) == 1

    def test_failed_instance_is_not_cached(self, monkeypatch):
        """连不上 Milvus（is_ready=False）→ **不缓存** → 下次请求重试。

        否则启动期的一次抖动会让这个进程永远检索不了。
        """
        import api.dependencies as deps

        class FakeRag:
            def __init__(self, model_manager):
                self.is_ready = False

        monkeypatch.setattr(deps, "RagModel", FakeRag)
        state = SimpleNamespace(model_manager="MGR")

        first = deps.get_rag_model(self._request(state))
        second = deps.get_rag_model(self._request(state))

        assert first is not second
        assert not hasattr(state, "rag_model")

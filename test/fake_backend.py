"""test/fake_backend.py —— 进程外假后端（E2E 用）。

为什么不用 Playwright 的 page.route()：
三个页面的后端调用都发生在 **Streamlit 服务端进程**里
（web_page/rag_page.py:37、web_page/rag_direct_page.py:27、web_page/repo_admin.py:35
的 requests.post），浏览器进程发出的请求根本不经过浏览器 → page.route() 一个都拦不到。
所以必须在进程外起一个真 HTTP 服务，让 Streamlit 通过 API_BASE_URL 指过来。

⚠️ 响应体形状必须**镜像真实契约**（设计文档 §3.5）：
- POST /agent/chat → {"response": ...}
    前端 rag_page.py:44 读 result["response"] → 少这个键会 KeyError → 页面显示"请求失败"
- POST /rag → {"response": ...}
    前端 rag_direct_page.py:33 读 .get("answer") → 返回 response 就落进 P1-1 固化用例
- POST /api/batch-upload-and-parse →
    {"status","message","upload_details":{"uploaded_files","skipped_files","failed_uploads"},
     "parse_results","note"}
    前端 repo_admin.py:44 读 data["upload_details"]["uploaded_files"] → 少这个键会 KeyError
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeBackendState:
    """假后端的可编程状态 —— 用例改这些字段来切换行为。"""

    def __init__(self):
        self.agent_answer = "这是假后端返回的 Agent 答案"
        self.rag_answer = "这是假后端返回的 RAG 答案"
        self.agent_status = 200
        self.rag_status = 200
        self.upload_status = 200
        self.uploaded_count = 1
        self.delay = 0.0
        self.port = 0
        self.requests: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        """静音 —— 假后端不需要刷屏。"""

    @property
    def state(self) -> FakeBackendState:
        return self.server.state

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"status": "ok"})

    def do_POST(self):
        state = self.state
        state.requests.append(self.path)
        self._read_body()
        if state.delay:
            time.sleep(state.delay)

        # ⚠️ self.path 带 query string（前端会传 ?overwrite=False），
        # 路由匹配必须先剥掉 "?..."，否则一律落到 404 分支。
        route = self.path.split("?", 1)[0]

        if route == "/agent/chat":
            self._send(state.agent_status, {"response": state.agent_answer})
        elif route == "/rag":
            self._send(state.rag_status, {"response": state.rag_answer})
        elif route == "/api/batch-upload-and-parse":
            self._send(
                state.upload_status,
                {
                    "status": "completed",
                    "message": (
                        f"批量上传完成：{state.uploaded_count}个成功，0个跳过，0个失败"
                    ),
                    "upload_details": {
                        "uploaded_files": [
                            {
                                "filename": f"probe_{index}.txt",
                                "save_path": f"/tmp/probe_{index}.txt",
                                "status": "新增",
                            }
                            for index in range(state.uploaded_count)
                        ],
                        "skipped_files": [],
                        "failed_uploads": [],
                    },
                    "parse_results": {},
                    "note": "假后端",
                },
            )
        else:
            self._send(404, {"detail": f"未实现的路径: {self.path}"})


def create_server():
    """起一个假后端，返回 (server, state)。端口随机，避开 8000 / 8501 / 8511。"""
    state = FakeBackendState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.state = state
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state

"""
简易"恶代理"：模拟当时 langchain_ollama 被本机代理拦截 /tokenize 的现象。

行为：
  - 监听 127.0.0.1:7890
  - 把所有请求转发到 127.0.0.1:11434 的真 Ollama
  - 但对 /api/tokenize 路径返回 502 Bad Gateway
    （模拟代码注释里说的"被代理拦到错误端口"）

用法：
  # 终端1: 启动恶代理
  python test/evil_proxy.py

  # 终端2: 让 HTTP 客户端强制走这个代理
  HTTP_PROXY=http://127.0.0.1:7890 python test/repro_embed_clients.py
  # 注意：本机已设的 NO_PROXY 必须清掉才能强制走代理：
  # unset NO_PROXY no_proxy
"""

import http.server
import socketserver
import urllib.request


OLLAMA_BASE = "http://127.0.0.1:11434"
LISTEN_ADDR = ("127.0.0.1", 7890)


class EvilProxyHandler(http.server.BaseHTTPRequestHandler):
    """拦 /tokenize，其他全部透传到真 Ollama。"""

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def _proxy(self):
        # 关键拦截：模拟代理把 /tokenize 拦走、返回错误
        if "/tokenize" in self.path:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(
                b"Bad Gateway: blocked by upstream proxy on port 52266"
            )
            print(f"  [拦截] {self.command} {self.path} → 502")
            return

        # 其他路径透传到真 Ollama
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None
        target = OLLAMA_BASE + self.path
        try:
            req = urllib.request.Request(
                target,
                data=body,
                method=self.command,
                headers={
                    k: v
                    for k, v in self.headers.items()
                    if k.lower() not in ("host", "content-length", "proxy-connection")
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
            print(f"  [透传] {self.command} {self.path} → {resp.status}")
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Proxy error: {e}".encode())
            print(f"  [错误] {self.command} {self.path} → {e}")

    def log_message(self, fmt, *args):
        # 关闭默认的 stderr 噪音
        pass


if __name__ == "__main__":
    print(f"[evil_proxy] 监听 {LISTEN_ADDR}，目标 {OLLAMA_BASE}")
    print(f"[evil_proxy] 拦截: /api/tokenize → 502")
    print(f"[evil_proxy] 透传: 其他路径 → Ollama")
    print(f"[evil_proxy] Ctrl+C 停止\n")
    with socketserver.ThreadingTCPServer(LISTEN_ADDR, EvilProxyHandler) as srv:
        srv.serve_forever()

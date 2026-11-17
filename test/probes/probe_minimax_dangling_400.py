"""探针：直连 MiniMax API ——「有 tool_calls 但没有 tool 应答」到底会不会 400？

场景 A：assistant 发了 tool_calls，但没有 tool 应答 → 预期 400
场景 B：同样的 tool_calls，补上 tool 应答 → 预期 200（对照组）

这是外部系统的硬约束，我们改不了 MiniMax，只能保证自己不造出这种消息序列。
需要 .env 里的 MINIMAX_BASE_URL / MINIMAX_API_KEY。
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env", override=True)

BASE = os.environ["MINIMAX_BASE_URL"].rstrip("/")
KEY = os.environ["MINIMAX_API_KEY"]
MODEL = "MiniMax-M3.1-Flash"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "rag_search",
        "description": "在知识库中检索资料",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}]

CALL_ID = "call-a2b31e24-fb66-4580-8386-52756b6a7307"

BODY_A = {
    "model": MODEL,
    "messages": [
        {"role": "user", "content": "帮我查一下 agent 学习笔记的要点"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": CALL_ID,
                "type": "function",
                "function": {"name": "rag_search", "arguments": '{"query": "agent 学习笔记"}'},
            }],
        },
    ],
    "tools": TOOLS,
    "temperature": 0.7,
    "max_tokens": 512,
}

BODY_B = json.loads(json.dumps(BODY_A))
BODY_B["messages"].append({
    "role": "tool",
    "tool_call_id": CALL_ID,
    "content": "这是检索到的知识库内容。",
})

HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def run(tag: str, body: dict) -> None:
    print(f"\n===== {tag} =====")
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=HEADERS, json=body, timeout=90)
        print(f"HTTP {r.status_code}")
        try:
            data = r.json()
        except Exception:
            print(r.text[:800])
            return
        if r.status_code != 200:
            print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
        else:
            msg = data.get("choices", [{}])[0].get("message", {})
            print("content:", (msg.get("content") or "")[:200])
            print("tool_calls:", msg.get("tool_calls"))
    except Exception as e:
        print(f"请求异常: {type(e).__name__}: {e}")


def main() -> None:
    run("A 悬空 tool_calls（无 tool 应答）", BODY_A)
    run("B 对照组（有 tool 应答）", BODY_B)


if __name__ == "__main__":
    main()

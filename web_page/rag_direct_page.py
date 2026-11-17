"""web_page/rag_direct_page.py —— 直连 /rag 的简单问答页面（无 Agent 编排）。"""
import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


def rag_direct_page():
    st.title("📖 知识库问答（直连 RAG）")
    st.caption("绕过 Agent，直接调 /rag 端点，证明 RAG 组件独立可用")

    if "rag_messages" not in st.session_state:
        st.session_state.rag_messages = []

    for msg in st.session_state.rag_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("问个问题（仅查知识库）"):
        st.session_state.rag_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("检索中..."):
                try:
                    r = requests.post(
                        f"{API_BASE}/rag",
                        json={"query": prompt},
                        timeout=60,
                    )
                    if r.status_code == 200:
                        # 后端 /rag 的契约是 ChatResponse{response}（api/api_rag.py）
                        answer = r.json().get("response", "(无答案)")
                    else:
                        answer = f"HTTP {r.status_code}: {r.text}"
                except Exception as e:
                    answer = f"请求失败：{e}"
                st.markdown(answer)

        st.session_state.rag_messages.append({"role": "assistant", "content": answer})

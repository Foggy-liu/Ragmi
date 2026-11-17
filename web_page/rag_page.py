import os

import streamlit as st
from streamlit_extras.bottom_container import bottom
import requests

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


def rag_page():
    # 全局初始化
    if "history" not in st.session_state:
        st.session_state.history = []

    AVATARS = {
        "user": "documents/img/human.png",
        "assistant": "documents/img/robot.png"
    }

    # 标题
    st.title("智能问答系统")

    # 对话历史
    for msg in st.session_state.history:
        with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
            st.markdown(msg["content"])

    # 输入区域
    with bottom():
        left, mid, right = st.columns([0.08, 0.84, 0.08])
        with left:
            st.button("⚙️", help="模型配置", use_container_width=True)
        with mid:
            query = st.chat_input("请输入问题...")
            if query:
                # 添加用户消息
                st.session_state.history.append({"role": "user", "content": query})

                # 调用Agent接口（统一入口）
                try:
                    response = requests.post(
                        url=f"{API_BASE}/agent/chat",
                        json={"query": query},
                        timeout=60
                    )
                    response.raise_for_status()
                    result = response.json()
                    ai_response = result["response"]
                except Exception as e:
                    ai_response = f"请求失败：{str(e)}"

                # 添加AI回复
                st.session_state.history.append({"role": "assistant", "content": ai_response})
                st.rerun()
        with right:
            if st.button("🗑️", help="清空对话", use_container_width=True):
                st.session_state.history = []
                st.rerun()


if __name__ == "__main__":
    rag_page()

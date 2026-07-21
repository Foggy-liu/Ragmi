"""main_web.py —— Streamlit 入口，三页面布局。

1. Agent 智能问答（默认）—— 走 /agent/chat
2. RAG 知识库问答 —— 直连 /rag，进阶证明
3. 仓库管理配置 —— 上传文件、查看状态（R0 仅上传）
"""
import streamlit as st
import streamlit_antd_components as sac

from web_page.rag_page import rag_page
from web_page.rag_direct_page import rag_direct_page
from web_page.repo_admin import repo_admin_page

st.set_page_config(page_title="RAGMI", layout="centered")

st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] {
        width: 300px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    selected_page = sac.menu(
        [
            sac.MenuItem("智能问答", icon="chat"),
            sac.MenuItem("知识库问答", icon="book"),
            sac.MenuItem("仓库管理配置", icon="hdd-stack"),
        ],
        key="selected_page",
        open_index=0,
    )

if selected_page == "知识库问答":
    rag_direct_page()
elif selected_page == "仓库管理配置":
    repo_admin_page()
else:
    rag_page()  # Agent 智能问答（默认）

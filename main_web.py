"""
UI界面主文件入口，左侧边栏设置
"""

# 导入streamlit库，用于构建Web界面
import streamlit as st
# 导入streamlit_antd_components库，用于构建UI组件
import streamlit_antd_components as sac
# 导入对话页面
from web_page.dialogue_page import dialogue_page
# 导入知识库管理页面
from web_page.knowledge_base import knowledge_base_page
# 导入MCP管理页面
from web_page.mcp import mcp_page
from web_page.rag_page import rag_page

if __name__ == '__main__':
    # 设置页面配置：标题为"LangChain-Chatchat"，布局为居中模式（实现 Streamlit 中聊天区域固定长度不随侧边栏伸缩变化）
    st.set_page_config(page_title="LangChain-Chatchat", layout="centered")

    st.markdown("""
    <style>   
    section[data-testid="stSidebar"] {
        width: 300px !important;
    }
    </style>
    """, unsafe_allow_html=True)


    # 创建左侧边栏容器
    with st.sidebar:

        # 创建单选按钮组，用于切换不同功能模块："多功能对话"、"RAG 对话"、"知识库管理"
        selected_page = sac.menu(
            [
                sac.MenuItem("多功能对话", icon="chat"),
                sac.MenuItem("RAG对话", icon="chat-left-text"),
                sac.MenuItem("知识库管理", icon="hdd-stack"),
                sac.MenuItem("MCP 管理", icon="plug"),
            ],
            key="selected_page",
            open_index=0,
        )

    # 根据用户选择，显示对应的功能模块，需要在with st.sidebar:之外实现，不然调用的函数会在左侧边栏内显示
    if selected_page == "RAG对话":
        rag_page()
    elif selected_page == "知识库管理":
        knowledge_base_page()
    elif selected_page == "MCP 管理":
        mcp_page()
    else:
        dialogue_page() # 右侧显示对话页面（你在包里实现的 UI）


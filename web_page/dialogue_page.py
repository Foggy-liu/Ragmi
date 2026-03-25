import streamlit as st
from streamlit_extras.bottom_container import bottom
import requests


def dialogue_page():
    # 1. 全局初始化：仅用 session_state 存历史（唯一数据源）
    if "history" not in st.session_state:
        st.session_state.history = []

    # 2. 全局头像配置（只写一次）
    AVATARS = {
        "user": "documents/img/human.png",
        "assistant": "documents/img/robot.png"
    }

    def left_sidebar():
        with st.sidebar:
            tool_tab, conv_tab = st.tabs(["工具设置", "会话设置"])
            with tool_tab:
                st.checkbox("启用Agent", help="请确保所选模型具备 Agent 能力")
                st.checkbox("显示 Agent 过程")
                st.checkbox("启用 RAG")
                st.selectbox("选择工具", ["None", "Tool-A", "Tool-B"])
                # st.subheader("上传图片")
                # st.file_uploader("Drag and drop file here", type=["bmp", "jpg", "jpeg", "png"])
                # st.button("黏贴图像")
            with conv_tab:
                st.text_input("会话名称")
                st.button("新建会话")
                st.button("重命名会话")
                st.button("删除会话")
                st.button("导出记录")
                if st.button("清空对话"):
                    st.session_state.history = []
                    st.rerun()

    def main():
        # 3. 渲染历史消息（原生组件，遍历一次就是一次，绝对不重复）
        for msg in st.session_state.history:
            with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
                st.markdown(msg["content"])

        # 4. 输入新消息（仅修改数据源，触发重渲染）
        with bottom():
            left, mid, right = st.columns([0.08, 0.84, 0.08])
            with left:
                st.button("⚙️", help="模型配置", use_container_width=True)
            with mid:
                query = st.chat_input("请输入对话内容，换行请使用Shift+Enter。")
                if query:
                    # 添加用户消息到历史
                    st.session_state.history.append({"role": "user", "content": query})

                    # 调用API获取AI回复
                    try:
                        response = requests.post(
                            url="http://localhost:8000/chat",
                            json={"query": query},
                            timeout=30
                        )
                        response.raise_for_status()
                        ai_response = response.json()["response"]
                    except Exception as e:
                        ai_response = f"请求失败: {str(e)}"

                    # 添加AI回复到历史
                    st.session_state.history.append({"role": "assistant", "content": ai_response})
                    st.rerun()
            with right:
                if st.button("🗑️", help="清空对话", use_container_width=True):
                    st.session_state.history = []
                    st.rerun()

    left_sidebar()
    main()


if __name__ == "__main__":
    dialogue_page()

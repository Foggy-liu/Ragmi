import streamlit as st

def knowledge_base_page():
    """
    知识库页面管理
    :return:
    """

    with st.sidebar:

        # 分割线
        st.divider()

        # 1. 查询关键字输入框
        st.write("查询关键字")
        keyword = st.text_input(
            label="",
            label_visibility="collapsed",
            placeholder="请输入查询关键字"
        )

        # 2. 匹配条数滑块
        st.write("匹配条数")
        match_count = st.slider(
            label="",
            min_value=1,
            max_value=100,
            value=3,
            label_visibility="collapsed",
            format="%d"  # 显示整数
        )


    # ---- 知识库管理页面 ----
    # 1.1. 知识库选择下拉框
    st.write("请选择或新建知识库:")
    kb_options = ["现有知识库1", "现有知识库2", "新建知识库"]  # 示例选项
    selected_kb = st.selectbox(
        label="",
        options=kb_options,
        label_visibility="collapsed",
        placeholder="选择知识库"
    )

    # 当选择“新建知识库”时，显示表单
    if selected_kb == "新建知识库":
        # 用st.container(border=True)实现带边框的表单区域
        with st.container(border=True):
            # 新建知识库名称
            kb_name = st.text_input(
                "新建知识库名称",
                placeholder="新知识库名称，不支持中文命名"
            )

            # 知识库简介
            kb_desc = st.text_input(
                "知识库简介",
                placeholder="知识库简介，方便Agent查找"
            )

            # 向量库类型下拉框
            vs_type = st.selectbox(
                "向量库类型",
                options=["chromadb", "pinecone", "faiss"],
                index=0
            )

            # Embeddings模型下拉框
            embed_model = st.selectbox(
                "Embeddings模型",
                options=["bge-large", "text-embedding-ada-002", "m3e-base"],
                index=0
            )

            # 新建按钮
            st.button("新建", use_container_width=True)


    # 2. 上传知识文件区域（自动生成所有提示文字）
    st.write("上传知识文件:")

    # 定义支持的文件格式列表（对应图中的格式）
    supported_file_types = [
        "HTML", "HTM", "MHTML", "MD", "JSON", "JSONL", "CSV", "PDF",
        "DOCX", "PPT", "PPTX", "PNG", "JPG", "JPEG", "BMP", "EML",
        "MSG", "RST", "RTF", "TXT", "XML", "EPUB", "ODT", "TSV",
        "IPYNB", "PY", "SRT", "TOML", "XLSX", "XLS", "XLSD", "ENEX"
    ]

    # 调用st.file_uploader，自动生成图中UI
    uploaded_files = st.file_uploader(
        label="",  # 隐藏组件自带的label（因为已经用st.write写了“上传知识文件:”）
        type=supported_file_types,  # 传入格式列表，组件会自动展示这些格式
        accept_multiple_files=True,
        label_visibility="collapsed"  # 隐藏组件默认label
    )

    # 3. 知识库介绍输入框
    st.write("请输入知识库介绍:")
    kb_desc = st.text_area(
        label="",
        value="关于chroma_data的知识库",
        label_visibility="collapsed",
        height=80
    )

    # 4. 文件处理配置（改用 st.expander 实现折叠面板）
    with st.expander("文件处理配置", expanded=True):
        # 单段文本最大长度 + 相邻文本重合长度 + 中文标题加强
        col1, col2, col3 = st.columns([2, 2, 3])
        with col1:
            st.write("单段文本最大长度:")
            max_len = st.number_input(
                label="",
                min_value=100,
                max_value=2000,
                value=750,
                step=50,
                label_visibility="collapsed"
            )
        with col2:
            st.write("相邻文本重合长度:")
            overlap_len = st.number_input(
                label="",
                min_value=0,
                max_value=500,
                value=150,
                step=10,
                label_visibility="collapsed"
            )
        with col3:
            st.write("")  # 占位
            title_boost = st.checkbox("开启中文标题加强")

    # 5. 添加文件到知识库按钮
    st.button("添加文件到知识库")

    # 分割线（视觉分隔）
    st.divider()

    # 6. 知识库空状态提示（改用 st.info 实现浅蓝色提示条）
    st.info("知识库 chroma_data 中暂无文件")

    # 分割线（视觉分隔）
    st.divider()

    # 7. 底部操作按钮（重建向量库 + 删除知识库）
    col_btn1, col_btn2 = st.columns([2, 3])  # 调整列宽比例，让按钮更美观
    with col_btn1:
        st.button("依据源文件重建向量库", type="primary")  # 蓝色主按钮
    with col_btn2:
        st.button("删除知识库")

    # 8. 文件列表说明文本
    st.write("文件内文档列表。双击进行修改，在删除列填入 y 可删除对应行。")

if __name__ == '__main__':
    knowledge_base_page()
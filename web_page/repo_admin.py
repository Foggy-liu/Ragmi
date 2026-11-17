"""web_page/repo_admin.py —— 仓库管理配置页面（R0：上传文件）。

后续扩展（不在本轮）：
- R1: 文件清单 + 删除按钮
- R2: 单文件重建
- R3: 多知识库切换
"""
import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


def repo_admin_page():
    st.title("📚 仓库管理配置")
    st.caption("上传文档到知识库（R0：仅上传功能）")

    st.subheader("上传文件")
    st.markdown(
        "支持类型：**PDF / Word(.docx) / Markdown / TXT**"
    )

    uploaded = st.file_uploader(
        "选择文件",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
    )

    if st.button("上传并解析", disabled=not uploaded):
        files = [
            ("files", (f.name, f.getvalue(), f.type))
            for f in uploaded
        ]
        try:
            r = requests.post(
                f"{API_BASE}/api/batch-upload-and-parse",
                files=files,
                params={"overwrite": False},
                timeout=300,
            )
            if r.status_code == 200:
                data = r.json()
                st.success(
                    f"完成：{len(data['upload_details']['uploaded_files'])} 个上传，"
                    f"{len(data['upload_details']['skipped_files'])} 个跳过，"
                    f"{len(data['upload_details']['failed_uploads'])} 个失败"
                )
                with st.expander("查看详情"):
                    st.json(data)
            else:
                st.error(f"上传失败：HTTP {r.status_code} - {r.text}")
        except Exception as e:
            st.error(f"请求失败：{e}")

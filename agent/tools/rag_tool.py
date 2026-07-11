"""agent/tools/rag_tool.py —— 把 RAGMI 现有 RAG 封装为 LangChain @tool。

v2 设计选择（rag_tool 是 LLM 唯一默认工具）：
1. docstring 写清"适用 / 不适用"——LLM 拿这段判断何时调
2. 返回纯文本（不带 sources 结构）
3. 懒加载 RagModel 单例——首次调用连接 Milvus，后续复用
"""

from langchain_core.tools import tool

from core.rags.rags import RagModel
from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel


_rag_model: RagModel | None = None


def _ensure_rag() -> RagModel:
    """懒加载 RAG 单例。复用 RAGMI 现有 ModelManager + LLMmodel 初始化逻辑。"""
    global _rag_model
    if _rag_model is None:
        manager = ModelManager()
        manager.load_config_models()
        default_model = LLMmodel()
        manager.set_current_model(default_model)
        _rag_model = RagModel(manager)
    return _rag_model


@tool
def rag_search(query: str) -> str:
    """从 RAGMI 个人知识库检索与 query 相关的内容。

    适用：
    - "我的 X" / "我最近的 X" / "你了解我..." 等个人上下文
    - 涉及用户上传过的文档 / 笔记 / 资料

    不适用：
    - 通用概念 / 原理（如"什么是 X 模式"）
    - 通用知识（如"河南大学在哪"）
    - 闲聊 / 问候
    """
    model = _ensure_rag()
    chunks = model._search_similar_chunks(query, top_k=5)
    if not chunks:
        return "（知识库中没有找到相关文档）"
    return "\n\n---\n\n".join(chunks)

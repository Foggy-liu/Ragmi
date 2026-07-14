"""agent/tools/rag_tool.py —— RAGMI 知识库检索工具（方案 2：1-LLM 路径）。

设计选择：
1. 只检索、不生成 —— 工具返回原始 chunks，最终答案由 agent LLM 自己综合
2. 走 RagModel.retrieve() 公开方法 —— 不穿透私有方法，未来 RAG 演进不影响 agent
3. 懒加载 RagModel 单例 —— 首次调用才连 Milvus，后续复用
4. 显式用 MiniMax-M3 —— 构造 RagModel 时指定（虽然方案 2 不用 RAG 内部 LLM，
   但 RagModel.__init__ 要求 model_manager，所以配一个真实的）
"""

from langchain_core.tools import tool

from core.rags.rags import RagModel
from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel


_rag_model: RagModel | None = None


def _ensure_rag() -> RagModel:
    """懒加载 RAG 单例。首次调用连接 Milvus + 初始化 embedding。"""
    global _rag_model
    if _rag_model is None:
        manager = ModelManager()
        manager.load_config_models()
        # 显式用 M3（RagModel 构造需要 model_manager，但方案 2 不调 RAG 内部 LLM）
        rag_llm = LLMmodel.create_minimax("MiniMax-M3")
        manager.set_current_model(rag_llm)
        _rag_model = RagModel(manager)
    return _rag_model


@tool
def rag_search(query: str) -> str:
    """从 RAGMI 个人知识库检索与 query 相关的内容片段。

    适用：
    - "我的 X" / "我最近的 X" / "你了解我..." 等个人上下文
    - 涉及用户上传过的文档 / 笔记 / 资料

    不适用：
    - 通用概念 / 原理（如"什么是 X 模式"）
    - 闲聊 / 问候

    返回：检索到的原始文档片段（多个片段用 --- 分隔）。
    工具不做最终综合，由 agent 基于这些片段自行作答。
    """
    model = _ensure_rag()
    chunks = model.retrieve(query, top_k=5)
    if not chunks:
        return "（知识库中没有找到相关文档）"
    return "\n\n---\n\n".join(chunks)
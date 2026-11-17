"""agent/tools/rag_tool.py —— RAGMI 知识库检索工具（方案 2：1-LLM 路径）。

设计选择：
1. 只检索、不生成 —— 工具返回原始 chunks，最终答案由 agent LLM 自己综合
2. 走 RagModel.retrieve() 公开方法 —— 不穿透私有方法，未来 RAG 演进不影响 agent
3. 懒加载 RagModel 单例 —— 首次调用才连 Milvus，后续复用
4. 显式用 MiniMax-M3.1-Flash —— 构造 RagModel 时指定（虽然方案 2 不用 RAG 内部 LLM，
   但 RagModel.__init__ 要求 model_manager，所以配一个真实的）
"""

from langchain_core.tools import tool

from agent.constants import TOOL_TIMEOUT
from agent.errors import AgentTimeoutError, AgentToolError, is_timeout
from agent.timeout import Timer
from core.rags.rags import RagModel, RetrievalError
from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel


_rag_model: RagModel | None = None


def _ensure_rag() -> RagModel:
    """懒加载 RAG 单例。首次调用连接 Milvus + 初始化 embedding。"""
    global _rag_model
    if _rag_model is None:
        manager = ModelManager()
        manager.load_config_models()
        # 显式用 M3.1-Flash（RagModel 构造需要 model_manager，但方案 2 不调 RAG 内部 LLM）
        rag_llm = LLMmodel.create_minimax("MiniMax-M3.1-Flash")
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

    检索为空时返回空字符串（v2.2）：不塞中文兜底串，否则 status_tool_wrapper
    永远判成 success，"检索为空"这个信号就丢了。空串由 wrapper 记为 status="empty"，
    再由 agent 综合节点据此改写答案。

    ⚠️ 检索**失败**（连不上 / 查询报错）不是"检索为空"——它抛 RetrievalError，
    这里翻译成 AgentTimeoutError / AgentToolError，wrapper 才能记成
    status="timeout" / "error" 而不是 "empty"（P2-7）。
    """
    model = _ensure_rag()
    try:
        chunks = Timer(TOOL_TIMEOUT).call(model.retrieve, query, top_k=5)
    except AgentTimeoutError:
        raise  # 已是归一化异常，原样上抛
    except RetrievalError as e:
        # 检索失败（P2-7）：按底层原因区分「超时」和「其他错误」——
        # 超时可重试（retryable=true），其他错重试没意义。
        cause = e.__cause__ if e.__cause__ is not None else e
        if is_timeout(cause):
            raise AgentTimeoutError(f"检索超时: {e}") from e
        raise AgentToolError(f"检索失败: {e}") from e
    except Exception as e:
        # 底层异常（Milvus/Ollama 的各种错）→ 翻译成归一化异常
        raise AgentToolError(f"检索失败: {type(e).__name__}: {e}") from e
    return "\n\n---\n\n".join(chunks)
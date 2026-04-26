"""
RAG Tool
封装RagModel，实现知识库问答
"""
from typing import Dict, Any, Optional
from agent.base.tool import BaseTool
from core.rags.rags import RagModel
from utils.models.model_manager import ModelManager


class RagTool(BaseTool):
    """知识库问答工具"""

    name = "rag"
    description = """基于知识库的问答工具。
当用户问题涉及具体事实、数据、文档内容，专业知识时使用。
会检索向量数据库中的相关文档片段并回答。"""

    def __init__(self, model_manager: ModelManager):
        self.rag_model = RagModel(model_manager)

    def invoke(self, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        执行RAG检索

        Args:
            query: 用户问题
            session_id: 会话ID

        Returns:
            {
                "response": str,      # RAG回答
                "tool_name": "rag",
                "confidence": str     # 置信度说明
            }
        """
        try:
            result = self.rag_model.chat(query, session_id)
            return {
                "response": result["response"],
                "tool_name": self.name,
                "confidence": "基于知识库检索"
            }
        except Exception as e:
            return {
                "response": f"RAG检索失败：{str(e)}",
                "tool_name": self.name,
                "confidence": "错误"
            }

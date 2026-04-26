"""
Chat Tool
封装ChatModel，实现普通对话
"""
from typing import Dict, Any, Optional
from agent.base.tool import BaseTool
from core.chat.chat import ChatModel
from utils.models.model_manager import ModelManager


class ChatTool(BaseTool):
    """普通对话工具"""

    name = "chat"
    description = """普通对话工具。
适用于日常聊天、创意写作、代码编写、逻辑推理、数学计算等不需要外部知识的场景。
基于训练数据和对话历史直接回答。"""

    def __init__(self, model_manager: ModelManager):
        self.chat_model = ChatModel(model_manager)

    def invoke(self, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        执行普通对话

        Args:
            query: 用户问题
            session_id: 会话ID

        Returns:
            {
                "response": str,      # 回答
                "tool_name": "chat",
                "confidence": str     # 置信度说明
            }
        """
        try:
            result = self.chat_model.chat(query, session_id)
            return {
                "response": result["response"],
                "tool_name": self.name,
                "confidence": "通用对话"
            }
        except Exception as e:
            return {
                "response": f"对话失败：{str(e)}",
                "tool_name": self.name,
                "confidence": "错误"
            }

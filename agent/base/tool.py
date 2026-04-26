"""
抽象Tool基类
所有Tool必须实现此接口，确保Agent与具体工具解耦
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseTool(ABC):
    """Tool抽象基类"""

    name: str           # 工具名称
    description: str    # 工具描述（用于LLM决策）

    @abstractmethod
    def invoke(self, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        执行工具

        Args:
            query: 用户问题
            session_id: 会话ID

        Returns:
            {
                "response": str,      # 工具执行结果
                "tool_name": str,     # 工具名称
                "confidence": str      # 置信度说明
            }
        """
        pass

    def get_langchain_tool(self):
        """
        转换为LangChain Tool对象（可选实现）
        用于未来接入LangChain Agent框架
        """
        return None

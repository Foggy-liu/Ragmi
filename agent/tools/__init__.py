"""Agent 工具层 —— LLM 可调用的能力（rag_search / calculator / weather / web_search）。

v2.2 扩展：ALL_TOOLS 从 1 个（rag_search）扩展为 4 个。
ALL_TOOLS 顺序由 LangGraph bind_tools 使用，建议工具调用频率高的在前。
"""
from .rag_tool import rag_search
from .calculator_tool import calculator
from .weather_tool import weather
from .web_search_tool import web_search

ALL_TOOLS = [rag_search, calculator, weather, web_search]
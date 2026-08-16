"""web_search 工具 —— v2.2 占位实现。

v2.2 范围仅占位；真实搜索引擎 API 后续 spec 替换。
"""
from langchain_core.tools import tool


@tool
def web_search(query: str) -> str:
    """网络搜索（占位实现，返回固定字符串）。

    Args:
        query: 搜索关键词

    Returns:
        固定占位字符串。
    """
    return f"占位：{query} 的搜索结果"
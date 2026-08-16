"""weather 工具 —— v2.2 占位实现。

v2.2 范围仅占位；真实天气 API 后续 spec 替换。
"""
from langchain_core.tools import tool


@tool
def weather(location: str) -> str:
    """查询某地天气（占位实现，返回固定字符串）。

    Args:
        location: 地点名称，例如 "北京"

    Returns:
        固定占位字符串。
    """
    return f"占位：{location} 今天 25℃ 晴"
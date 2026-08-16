"""calculator 工具 —— v2.2 占位实现。

v2.2 范围仅占位；真实数值计算后续 spec 替换。
"""
from langchain_core.tools import tool


@tool
def calculator(expression: str) -> str:
    """计算数学表达式。

    Args:
        expression: 数学表达式字符串，例如 "2+3*4"

    Returns:
        计算结果字符串。eval 失败时返回错误说明。
    """
    try:
        return str(eval(expression))
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
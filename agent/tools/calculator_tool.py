"""calculator 工具 —— v2.2 占位实现。

⚠️ 这里**不能用 eval()**（P1-2）：LLM 的输出是**不可信输入**，
`eval("__import__('os').system('...')")` 就是一次远程代码执行 ——
一次提示词注入就能让 Agent 在宿主机上跑任意命令。

改成 AST 白名单求值：只认**数字**和 **+ - * / // % ** 与括号**，
其余语法（函数调用、属性访问、变量名、导入、字符串）一律拒绝。
"""
import ast
import operator

from langchain_core.tools import tool

# AST 节点类型 → 运算函数。白名单之外的节点一律拒绝。
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# 表达式长度上限 —— 防止超长表达式拖慢解析
_MAX_EXPRESSION_LEN = 200
# 指数上限 —— 2**10**9 会把内存吃光（LLM 输出的 DoS 面）
_MAX_EXPONENT = 100


def _eval_node(node: ast.AST):
    """递归求值 AST 节点。遇到白名单外的节点直接抛异常。"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        # bool 是 int 的子类，要单独挡掉（True 会被当成 1）
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"只支持数字，收到 {type(node.value).__name__}")
        return node.value

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op is operator.pow and abs(right) > _MAX_EXPONENT:
            raise ValueError(f"指数过大（上限 {_MAX_EXPONENT}）")
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
        return op(_eval_node(node.operand))

    raise ValueError(f"不支持的表达式: {type(node).__name__}")


@tool
def calculator(expression: str) -> str:
    """计算数学表达式。

    Args:
        expression: 数学表达式字符串，例如 "2+3*4"

    Returns:
        计算结果字符串。表达式非法时返回错误说明。
    """
    if len(expression) > _MAX_EXPRESSION_LEN:
        return f"ERROR: 表达式过长（上限 {_MAX_EXPRESSION_LEN} 字符）"
    try:
        # strip()：ast.parse 不吃前导空白（会报 IndentationError），但 eval() 吃
        tree = ast.parse(expression.strip(), mode="eval")
        return str(_eval_node(tree))
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

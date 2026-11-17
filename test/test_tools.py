"""test/test_tools.py —— 工具层的纯函数测试（永远跑）。

测 agent/tools/ 下不依赖 Milvus / LLM 的那部分逻辑。
- calculator —— 它以前用 eval() 执行 LLM 传来的字符串，等于把 RCE
  交给模型（P1-2）。这里的用例把"白名单之外一律拒绝"钉死。
- rag_search 的**异常归一化** —— "检索失败"不能被降级成"检索为空"（P2-7）。

不连 Milvus、不调真 LLM。
"""
import httpx
import pytest

from agent.errors import AgentTimeoutError, AgentToolError
from agent.tools.calculator_tool import calculator
from agent.tools.rag_tool import rag_search
from core.rags.rags import RetrievalError


def _calc(expression: str) -> str:
    """调工具本体（绕开 LangChain 的参数解析，只测求值逻辑）。"""
    return calculator.invoke({"expression": expression})


class TestCalculatorArithmetic:
    """正常算术 —— 白名单内的语法必须算对。"""

    def test_simple_addition(self):
        assert _calc("2+3") == "5"

    def test_operator_precedence(self):
        """乘法优先于加法。"""
        assert _calc("2+3*4") == "14"

    def test_parentheses(self):
        assert _calc("(2+3)*4") == "20"

    def test_float_division(self):
        assert _calc("10/4") == "2.5"

    def test_power(self):
        assert _calc("2**10") == "1024"

    def test_modulo(self):
        assert _calc("7%3") == "1"

    def test_unary_minus(self):
        assert _calc("-5+3") == "-2"

    def test_whitespace_tolerated(self):
        assert _calc("  7 * 6  ") == "42"


class TestCalculatorRejectsUnsafeInput:
    """不安全输入 —— 白名单之外一律拒绝，不执行。"""

    def test_rejects_os_system_call(self):
        """最经典的 RCE：__import__('os').system(...)"""
        result = _calc("__import__('os').system('echo pwned')")

        assert result.startswith("ERROR:")
        assert "pwned" not in result

    def test_rejects_builtin_call(self):
        """open(...).read() —— 读文件。"""
        result = _calc("open('/etc/passwd').read()")

        assert result.startswith("ERROR:")

    def test_rejects_attribute_access(self):
        """哪怕对象不是调用，属性访问本身也不该过。"""
        result = _calc("().__class__")

        assert result.startswith("ERROR:")

    def test_rejects_string_constant(self):
        result = _calc("'abc'")

        assert result.startswith("ERROR:")

    def test_rejects_boolean(self):
        """bool 是 int 的子类 —— True 不能当 1 混进去。"""
        result = _calc("True + 1")

        assert result.startswith("ERROR:")

    def test_rejects_name_lookup(self):
        """变量名 —— 没有命名空间可查。"""
        result = _calc("x + 1")

        assert result.startswith("ERROR:")

    def test_rejects_oversized_exponent(self):
        """2**10**9 会把内存吃光 —— 指数必须封顶。"""
        result = _calc("2**100000")

        assert result.startswith("ERROR:")

    def test_rejects_oversized_expression(self):
        result = _calc("1+" * 200 + "1")

        assert result.startswith("ERROR:")

    def test_division_by_zero_is_error_not_crash(self):
        result = _calc("1/0")

        assert result.startswith("ERROR:")

    def test_syntax_error_is_reported(self):
        result = _calc("2 +")

        assert result.startswith("ERROR:")


@pytest.mark.parametrize("expression", ["", "   ", "()", "1+"])
def test_malformed_input_returns_error_not_exception(expression):
    """任何畸形输入都只能返回 ERROR 字符串，不能抛异常穿出去。"""
    result = _calc(expression)

    assert isinstance(result, str)
    assert result.startswith("ERROR:")


class TestRagSearchExceptionTranslation:
    """检索工具的异常归一化 —— **"检索失败" ≠ "检索为空"**（P2-7）。

    修之前 `core/rags/rags.py` 把所有异常吞成 `[]`，
    工具层只能记 `status="empty"` —— Agent 分不清
    「知识库里没这条」和「知识库挂了」。
    """

    @staticmethod
    def _install_fake_rag(monkeypatch, error):
        """把工具底下那一层换成一个「一调用就抛错」的假检索。"""
        import agent.tools.rag_tool as rag_tool

        class BoomRag:
            def retrieve(self, query, top_k=5):
                raise error

        monkeypatch.setattr(rag_tool, "_ensure_rag", lambda: BoomRag())

    def test_retrieval_error_becomes_agent_tool_error(self, monkeypatch):
        """检索失败（RetrievalError）→ AgentToolError（不可重试）。"""
        self._install_fake_rag(monkeypatch, RetrievalError("Milvus 查询失败"))

        with pytest.raises(AgentToolError) as excinfo:
            rag_search.invoke({"query": "q"})

        assert "Milvus 查询失败" in str(excinfo.value)

    def test_retrieval_error_caused_by_timeout_becomes_agent_timeout_error(self, monkeypatch):
        """RetrievalError 的**底层原因是超时** → AgentTimeoutError（可重试）。

        这是 P2-8 的直接后果：给 Ollama 客户端加了 timeout 之后，
        超时真的会从底层冒出来 —— 必须翻译成"超时"而不是"其他错误"，
        否则 status 会记成 error 而不是 timeout。
        """
        try:
            raise httpx.ReadTimeout("read timed out")
        except httpx.ReadTimeout as e:
            error = RetrievalError("相似度搜索失败：ReadTimeout")
            error.__cause__ = e

        self._install_fake_rag(monkeypatch, error)

        with pytest.raises(AgentTimeoutError):
            rag_search.invoke({"query": "q"})

    def test_unexpected_error_still_becomes_agent_tool_error(self, monkeypatch):
        """没被归一化的第三方异常 → AgentToolError（老行为不变）。"""
        self._install_fake_rag(monkeypatch, RuntimeError("Milvus 连不上"))

        with pytest.raises(AgentToolError) as excinfo:
            rag_search.invoke({"query": "q"})

        assert "Milvus 连不上" in str(excinfo.value)

    def test_empty_result_is_returned_as_empty_string(self, monkeypatch):
        """检索到 0 条 → 返回空串（不是异常）—— "为空"和"失败"两条路。"""
        import agent.tools.rag_tool as rag_tool

        class EmptyRag:
            def retrieve(self, query, top_k=5):
                return []

        monkeypatch.setattr(rag_tool, "_ensure_rag", lambda: EmptyRag())

        assert rag_search.invoke({"query": "q"}) == ""

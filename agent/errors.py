"""agent/errors.py —— Agent 归一化异常 + 原始超时识别。

为什么需要归一化：
工具层底下是一堆第三方库的异常（httpx.ReadTimeout / pymilvus 的各种错 /
openai.APITimeoutError ...），类名各不相同、继承关系互不相干。
上层节点只想知道两件事：
    1. 是不是超时？→ 该不该重试
    2. 还是别的错？→ 直接放弃
所以在「离异常最近的地方」（工具函数里）把它们翻译成两个语义清晰的异常，
上层只认这两个。

异常层次：
    Exception
     └─ AgentError          Agent 内部可预期错误的基类
         ├─ AgentTimeoutError   超时 —— 可重试（网络抖动）
         └─ AgentToolError      工具失败 —— 不可重试（参数错/服务挂/代码 bug）

异常翻译的三跳（⚠️ 这是"错误叫什么"的链路，**不是超时层** ——
超时只有两层计时，见 agent/timeout.py）：
    第 1 跳  原始异常（httpx.ReadTimeout 等）
              ↓ agent/tools/rag_tool.py 翻译
    第 2 跳  归一化异常（AgentTimeoutError / AgentToolError）
              ↓ agent/nodes/status_tool_wrapper.py 翻译
    第 3 跳  业务状态（tool_status = {"rag_search": "timeout"}）→ 给 LLM 看
"""
import httpx

# 各家库的超时异常统一收口：
#   builtin TimeoutError —— 含 socket.timeout（Python 3.10 起二者是同一个类）
#   httpx.TimeoutException —— httpx 所有超时的父类；openai.APITimeoutError 继承自它
_RAW_TIMEOUT_EXC = (TimeoutError, httpx.TimeoutException)


class AgentError(Exception):
    """Agent 内部可预期错误的基类。"""


class AgentTimeoutError(AgentError):
    """超时。语义：可重试 —— 同样的调用再来一次可能就成功了。"""


class AgentToolError(AgentError):
    """工具执行失败（非超时）。语义：不可重试 —— 再调一次还是错。"""


def is_timeout(exc: BaseException) -> bool:
    """判断一个原始异常是不是超时类。

    先用精确的类型判断，再用类名兜底（覆盖 grpc.FutureTimeoutError 这类
    不在 httpx 体系里的超时异常）。
    """
    if isinstance(exc, _RAW_TIMEOUT_EXC):
        return True
    return "timeout" in type(exc).__name__.lower()

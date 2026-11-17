"""agent/timeout.py —— Agent 统一计时器 + 图级总时限。

两种计时，用途完全不同：

1. Timer —— 「单次动作级」。对任意同步调用施加时间上限。
             工具层用（rag_search 内部的 Ollama/Milvus 调用）。

2. deadline —— 「图级总时限」。写进 state，节点进图时问 is_expired()。
             解决「每一步都没超时，但加起来能跑到十几分钟」。

为什么 deadline 放 state 而不是全局变量：
state 是 LangGraph 里跨节点传递数据的唯一通道，且**每次 invoke 天然隔离**
——两个并发请求各有一份 state，不会互相污染。全局变量做不到这点。
"""
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from agent.constants import TOOL_TIMEOUT
from agent.errors import AgentTimeoutError, is_timeout


class Timer:
    """统一计时器：对同步可调用对象施加时间上限。

    用法：
        Timer(TOOL_TIMEOUT).call(model.retrieve, query, top_k=5)

    ⚠️ 已知限制：Python 杀不掉线程。超时后底层线程仍在跑、仍占着
       Milvus/Ollama 连接 —— 这是「超时兜底」，不是「强制中断」。
       真正的中断要靠底层客户端自己的 timeout（当前未做，记为已知局限）。
    """

    def __init__(self, timeout: float = TOOL_TIMEOUT):
        self.timeout = timeout

    def call(self, fn, /, *args, **kwargs):
        """执行 fn(*args, **kwargs)；超时抛 AgentTimeoutError。

        非超时异常**原样上抛**（不吞）—— 由调用方决定怎么翻译。
        """
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(fn, *args, **kwargs)
            return fut.result(timeout=self.timeout)
        except FutureTimeout:
            # 情况 A：外层等太久（底层客户端还没到点）
            raise AgentTimeoutError(f"调用超过 {self.timeout}s 未返回") from None
        except Exception as e:
            # 情况 B：底层自己抛了异常 → 超时就翻译，非超时就原样上抛
            if is_timeout(e):
                raise AgentTimeoutError(f"底层调用超时: {type(e).__name__}") from e
            raise
        finally:
            ex.shutdown(wait=False)   # ⚠️ 不能用 with —— with 退出会等线程跑完


def is_expired(state: dict) -> bool:
    """图级总时限检查。deadline 由 runtime.ask() 写进初始 state。"""
    deadline = state.get("deadline")
    return bool(deadline) and time.time() > deadline

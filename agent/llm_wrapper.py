"""agent/llm_wrapper.py —— 推理模型 think 块剥离包装 (v2.2 增量修复)。

背景：
MiniMax-M3 / M2.7、DeepSeek-R1、Qwen3-Thinking 等推理模型会在 AIMessage.content
里塞 <think>...</think> 块。这是模型架构决定的，prompt 关不掉，API 也没开关。

影响 v2.2 Agent：
1. 前端视觉脏：synth 输出的 AIMessage.content 含 think 块直接透传
2. messages 历史污染：含 think 的 AIMessage 加入 state["messages"]，
   后续 LLM 调用读 messages 时被 think 污染
3. reflect 解析失败：with_structured_output(Pydantic) 不能容忍 think 块 + Literal

本模块提供 LLM 客户端层的统一剥离：
- strip_thinking(content)：纯函数，剥 <think>...</think> 块
- ThinkingStripRunnable：包装任意 Runnable，invoke 返回前自动剥
  支持链式调用：bind_tools / with_config / with_structured_output

放在最底层包装，剥的是底层 AIMessage.content；所有派生（bind_tools / 结构化输出）
都基于已剥 think 的 AIMessage 工作。
"""
import re

from langchain_core.messages import AIMessage

# 匹配完整 think 块：<think> ... </think>（非贪婪、跨行）
_FULL_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(content: str) -> str:
    """剥离 ``<think>...</think>`` 块（兼容只有结束标签的情况）。空内容、非字符串直接返回。

    实际跑 RAGMI agent 时观察到 M2.7 两种 think 输出形式：
    1. 完整：`<think>思考\n</think>\n\n答案`（直接调 ChatOpenAI 测出）
    2. 孤儿：`思考\n</think>\n\n答案`（通过 LangGraph 调用时出现，无 ``<think>`` 开始）

    处理顺序：
    1. 先剥完整块（``<think>...</think>``）
    2. 再剥孤儿 ``</think>``（前面所有内容）—— 只剥第一个，保留后面答案
    """
    if not content:
        return content
    if not isinstance(content, str):
        return content

    # 第 1 步：剥完整块
    cleaned = _FULL_THINK_RE.sub("", content)

    # 第 2 步：处理孤儿 </think>
    # 注意：只剥到第一个 </think> 为止，避免误伤正文里合法出现 </think> 子串的极端情况
    if "</think>" in cleaned:
        idx = cleaned.find("</think>")
        cleaned = cleaned[idx + len("</think>"):]

    return cleaned.strip()


def _strip_aimessage(resp):
    """原地修改 AIMessage.content，返回原对象。

    只处理 AIMessage；其他类型（str / Pydantic 对象 / 异常）原样返回。
    """
    if isinstance(resp, AIMessage) and isinstance(resp.content, str):
        resp.content = strip_thinking(resp.content)
    return resp


class ThinkingStripRunnable:
    """包装 Runnable，invoke 返回前自动剥离 ``<think>...</think>``。

    设计目标：节点侧零感知——业务代码继续写 ``.invoke(prompt_messages)``，
    返回的 AIMessage.content 自动干净。

    支持链式调用：
    - ``bind_tools(tools)`` → 返回新包装（iter_node 用）
    - ``with_config(cfg)`` → 返回新包装（统一超时配置）
    - ``with_structured_output(schema)`` → 返回新包装（reflect_node 用）

    剥 think 放在最内层（self._base.invoke 返回前），保证 bind_tools /
    with_structured_output 等所有派生都能享受到剥离效果。
    """

    def __init__(self, base):
        self._base = base

    # ===== 主调用入口 =====
    def invoke(self, messages, **kw):
        resp = self._base.invoke(messages, **kw)
        return _strip_aimessage(resp)

    async def ainvoke(self, messages, **kw):
        resp = await self._base.ainvoke(messages, **kw)
        return _strip_aimessage(resp)

    # ===== 链式调用支持 =====
    def bind_tools(self, tools):
        """iter_node 用：包装派生 runnable（Function Calling 模式也剥 think）。"""
        return ThinkingStripRunnable(self._base.bind_tools(tools))

    def with_config(self, cfg):
        """统一超时 / run_name 配置。"""
        return ThinkingStripRunnable(self._base.with_config(cfg))

    def with_structured_output(self, schema):
        """reflect_node 用：包装结构化输出 runnable（剥 think 后 Pydantic 解析更稳）。"""
        return ThinkingStripRunnable(self._base.with_structured_output(schema))

    # ===== 透传未知方法（避免破坏 LangChain 内部依赖）=====
    def __getattr__(self, name):
        return getattr(self._base, name)

    def __repr__(self):
        return f"ThinkingStripRunnable({self._base!r})"
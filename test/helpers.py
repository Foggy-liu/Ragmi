"""test/helpers.py —— 测试公共工具（假 LLM / 假检索 / 断言工具）。

为什么需要这一层：
- 假 LLM 要能**按剧本**返回不同角色的内容，还要能记录每次收到的 prompt
  （F1c 的 grounding 断言依赖这个）
- 假检索只替换工具**底下那一层**（_ensure_rag），从而保留 Timer 计时 /
  异常归一化 / status_wrapper 这三段最该被测的真实代码
- 断言工具要能查"悬空 tool_calls"—— v2.2 修过的 bug 的回归护栏
"""
from __future__ import annotations

import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent.constants import INTERNAL_SIGNALS
from agent.runtime import RECURSION_LIMIT

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: Agent 内部占位消息 —— 不该出现在最终答案里
#: 从 agent.constants 导入而不是复制一份：复制就会漂移（改了产品侧忘了改测试侧，
#: "答案不是占位"这条断言就变成了永真）。
INTERNAL_PLACEHOLDERS = tuple(sorted(INTERNAL_SIGNALS))

#: 工具返回多段 chunk 时的分隔符（agent/tools/rag_tool.py:64）
CHUNK_SEPARATOR = "\n\n---\n\n"


# ---------------------------------------------------------------------------
# 消息构造
# ---------------------------------------------------------------------------

def tool_call_message(call_id: str, name: str = "rag_search", **args) -> AIMessage:
    """构造一条带 tool_calls 的 AIMessage。

    ⚠️ 每次调用都返回**全新对象** —— LangGraph 的 add_messages 按 message.id
    去重，复用同一个对象会被当成"更新"而不是"新增"。
    """
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {"query": "q"}, "id": call_id}],
    )


def ready_message() -> AIMessage:
    """iter 节点"不调工具"的信号消息。"""
    return AIMessage(content="READY")


# ---------------------------------------------------------------------------
# 假 LLM
# ---------------------------------------------------------------------------

class Script:
    """假 LLM 剧本：每个角色一条出牌列表，**用完后重复最后一项**。

    "重复最后一项"让"恒返回 re_iterate"这类场景一行就能表达。
    列表元素可以是正常返回值，也可以是**要抛出的异常实例**。

    ⚠️ 剧本末尾必须是"停"（如 ready_message()），否则 iter 会一直发工具调用
    直到打满 MAX_ITER —— 那测的就不是你想测的场景了。
    """

    def __init__(self, iter=None, synth=None, reflect=None):
        self.iter = list(iter or [])
        self.synth = list(synth or [])
        self.reflect = list(reflect or [])
        self.calls: list[tuple[str, list]] = []
        self.delays: dict[str, float] = {}
        self._cursor = {"iter": 0, "synth": 0, "reflect": 0}

    def play(self, role: str, messages):
        """按剧本出牌。异常实例会被 raise；消息会返回全新副本。"""
        self.calls.append((role, messages))
        if self.delays.get(role):
            time.sleep(self.delays[role])
        queue = getattr(self, role)
        if not queue:
            raise AssertionError(f"剧本里没有给 {role} 安排返回值")
        index = self._cursor[role]
        item = queue[min(index, len(queue) - 1)]
        self._cursor[role] = index + 1
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, BaseMessage):
            # 全新副本 → 新 id → add_messages 当成"新增"而不是"更新"
            return item.model_copy(update={"id": None})
        return item

    def count(self, role: str) -> int:
        """该角色被调用了几次（= LLM 真实调用次数）。"""
        return sum(1 for r, _ in self.calls if r == role)

    def prompts(self, role: str) -> list[str]:
        """该角色每次收到的 prompt 全文（拼成字符串）。"""
        return [
            "\n".join(str(m.content) for m in messages)
            for r, messages in self.calls if r == role
        ]


class _RoleView:
    """带角色的 chat 视图。

    角色由**调用位置**决定，不靠看 prompt：
    - bind_tools 只有 iter 调
    - with_structured_output 只有 reflect 调
    - 裸 invoke 只有 synth 调
    """

    def __init__(self, script: Script, role: str):
        self._script = script
        self._role = role

    def invoke(self, messages):
        return self._script.play(self._role, messages)


class FakeChat:
    """假的 chat 客户端（替代 ChatOpenAI）。"""

    def __init__(self, script: Script):
        self.script = script

    def invoke(self, messages):                   # synth 路径
        return self.script.play("synth", messages)

    def bind_tools(self, tools):                  # iter 路径
        return _RoleView(self.script, "iter")

    def with_structured_output(self, schema):     # reflect 路径
        return _RoleView(self.script, "reflect")


class FakeLLMInstance:
    """替代 LLMmodel.create_minimax() 的返回值。

    platform / model_name 必须存在 —— ModelManager.add_model 会读它们。
    """

    def __init__(self, script: Script):
        self.script = script
        self.chat = FakeChat(script)
        self.platform = "minimax"
        self.model_name = "MiniMax-M3.1-Flash"


# ---------------------------------------------------------------------------
# 假检索
# ---------------------------------------------------------------------------

class FakeRag:
    """假的 RagModel —— 只实现 retrieve()。

    可配置：返回 chunks / 返回 [] / 抛异常 / 睡 N 秒（配合 TOOL_TIMEOUT 造超时）。
    """

    def __init__(self, chunks=None, error=None, delay=0.0):
        self.chunks = list(chunks or [])
        self.error = error
        self.delay = delay
        self.calls: list[str] = []

    def retrieve(self, query, top_k=5):
        self.calls.append(query)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return list(self.chunks)


# ---------------------------------------------------------------------------
# 断言工具
# ---------------------------------------------------------------------------

def dangling_tool_calls(messages) -> list[str]:
    """找出没有对应 ToolMessage 应答的 tool_call id（"悬空"）。

    悬空 tool_calls 会让 MiniMax 报 HTTP 400（invalid params, tool call and
    result not match）—— v2.2 修过的 bug，这是它的回归护栏。
    """
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    result = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call["id"] not in answered:
                result.append(call["id"])
    return result


def tool_messages(messages) -> list[ToolMessage]:
    """所有 ToolMessage。"""
    return [m for m in messages if isinstance(m, ToolMessage)]


def ai_contents(messages) -> list[str]:
    """所有 AIMessage 的文本内容。"""
    return [m.content for m in messages if isinstance(m, AIMessage)]


def run_graph(graph, question="测试问题", deadline=None, **extra):
    """直接 invoke 图，绕开 runtime.ask() 写死的 90 秒 deadline。

    超时类用例（F9a/F9b/F9c）必须用它 —— ask() 不给控制 deadline 的口子
    （agent/runtime.py:95）。
    """
    state: dict = {"messages": [HumanMessage(content=question)]}
    if deadline is not None:
        state["deadline"] = deadline
    state.update(extra)
    return graph.invoke(state, config={"recursion_limit": RECURSION_LIMIT})

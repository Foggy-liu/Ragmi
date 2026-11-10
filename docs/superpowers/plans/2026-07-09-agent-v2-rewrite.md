# Agent v2 (LangGraph 重写) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 LangGraph + `bind_tools()` 重写 RAGMI 的 Agent 控制器，让 LLM 能自主决定调哪个工具 + 传什么参数，并在 12 个测试集上把"选对工具率"从 v1 基线提升到 ≥75%。

**Architecture:** Single Agent + Plan-and-Execute lite。`StateGraph` 包含 2 个节点（agent_node + ToolNode），条件边根据 LLM 是否输出 `tool_calls` 决定下一步。MemorySaver 做会话持久化。工具用 `@tool` 装饰器，参数结构化（top_k、filter 等）。

**Tech Stack:**
- LangGraph（`StateGraph`、`ToolNode`、`MemorySaver`）
- LangChain（`@tool`、`bind_tools`）
- 现有 `LLMmodel`（用阿里云 qwen3.5-plus，不支持 Ollama）
- 现有 `RagModel`、`MessageManager`（保留但用 LangGraph 方式访问）

---

## 〇、关键决策（避免中途纠结）

| 决策 | 选择 | 理由 |
|---|---|---|
| chat 工具要不要 | **不要** | LLM 不调工具时直接生成答案（LangGraph 默认行为） |
| RAG 工具返回类型 | **结构化 dict**（含 sources） | 面试能讲溯源 + 测试集能验证 |
| session_id 处理 | **LangGraph thread_id** | 替代 v1 全局 MessageManager 单例 |
| LLM 选什么 | **阿里云 qwen3.5-plus** | 支持 tool_calls；Ollama 不支持 |
| v1 代码 | **保留不动** | 面试故事 + git 历史 |

---

## 一、文件结构

```
agent_v2/                        # 新建
├── __init__.py
├── state.py                     # AgentState TypedDict
├── graph.py                     # StateGraph 装配
├── runtime.py                   # API 入口
├── nodes/
│   ├── __init__.py
│   ├── agent_node.py            # LLM 决策
│   └── should_continue.py       # 条件边函数
├── tools/
│   ├── __init__.py
│   ├── schemas.py               # Pydantic models
│   └── rag_search.py            # @tool RAG 工具
└── prompts/
    ├── __init__.py
    └── system_prompt.py         # 系统提示词

api/
└── api_agent_v2.py              # 新路由

test/
├── agent_test_cases.json        # 12 个测试 case
├── run_v1_baseline.py           # 跑 v1 拿基线
└── run_v2_eval.py               # 跑 v2 评估

main.py                          # 注册 v2 路由（不改逻辑）
```

**每个文件职责**：
- `state.py`：定义状态 schema（1 个文件 ≈ 20 行）
- `graph.py`：装配图（≈ 30 行）
- `runtime.py`：API 友好的包装（≈ 30 行）
- `nodes/agent_node.py`：纯函数，调 LLM 返回 AIMessage（≈ 15 行）
- `nodes/should_continue.py`：判断是否继续（≈ 15 行）
- `tools/schemas.py`：Pydantic Source 和 RagResult（≈ 30 行）
- `tools/rag_search.py`：@tool 装饰的 RAG 函数（≈ 40 行）
- `prompts/system_prompt.py`：系统提示词（≈ 30 行）
- `api/api_agent_v2.py`：FastAPI 路由（≈ 30 行）

---

## 二、任务列表

### Phase 1: 准备（Day 1）—— 4 个任务

#### Task 1: 重读 controller_lessons.md（30 分钟）

**Files:** Read `docs/note/controller_lessons.md`

- [ ] **Step 1: 通读 5 大问题**（15 分钟）

用 Read 工具读 `docs/note/controller_lessons.md` 的 §一和 §二。

- [ ] **Step 2: 写一段"我学到的"笔记**（15 分钟）

在 `docs/note/note_day1_react.md` 写 200 字：
> "v1 烂在哪，5 个问题中我重写时要重点避免哪 3 个？"

**验收**：200 字笔记写完，3 个具体问题列出来。

---

#### Task 2: 写 12 个测试 case（45 分钟）

**Files:**
- Create: `test/agent_test_cases.json`

- [ ] **Step 1: 写 12 个 case 的 JSON**

```json
[
  {
    "id": "T01",
    "query": "你是谁",
    "expected_tool": "chat",
    "category": "general",
    "reference_keywords": ["AI", "助手"]
  },
  {
    "id": "T02",
    "query": "1+1等于多少",
    "expected_tool": "chat",
    "category": "general",
    "reference_keywords": ["2"]
  },
  {
    "id": "T03",
    "query": "你好",
    "expected_tool": "chat",
    "category": "general",
    "reference_keywords": ["你好"]
  },
  {
    "id": "T04",
    "query": "在我的知识库里有什么内容",
    "expected_tool": "rag",
    "category": "knowledge_lookup",
    "note": "v1 失败 case，v2 必须选对"
  },
  {
    "id": "T05",
    "query": "我之前上传的文档讲了什么",
    "expected_tool": "rag",
    "category": "knowledge_lookup"
  },
  {
    "id": "T06",
    "query": "劳动合同法第36条是什么",
    "expected_tool": "rag",
    "category": "knowledge_lookup"
  },
  {
    "id": "T07",
    "query": "Python 的 list 和 tuple 有什么区别",
    "expected_tool": "chat",
    "category": "general"
  },
  {
    "id": "T08",
    "query": "你了解我最近读的书吗",
    "expected_tool": "rag",
    "category": "knowledge_lookup"
  },
  {
    "id": "T09",
    "query": "上海今天天气怎么样",
    "expected_tool": "chat",
    "category": "rag_empty",
    "note": "没有天气工具，应该走 chat"
  },
  {
    "id": "T10",
    "query": "介绍下 LangGraph",
    "expected_tool": "chat",
    "category": "general"
  },
  {
    "id": "T11",
    "query": "我的简历里有什么",
    "expected_tool": "rag",
    "category": "knowledge_lookup"
  },
  {
    "id": "T12",
    "query": "解释下什么是 ReAct 模式",
    "expected_tool": "chat",
    "category": "general"
  }
]
```

- [ ] **Step 2: 验证 JSON 格式正确**

Run: `python -c "import json; data = json.load(open('test/agent_test_cases.json', 'r', encoding='utf-8')); print(f'{len(data)} cases')"`
Expected: `12 cases`

- [ ] **Step 3: Commit**

```bash
git add test/agent_test_cases.json
git commit -m "test: add 12 agent test cases for v1/v2 evaluation"
```

---

#### Task 3: 写 v1 baseline 跑分脚本（45 分钟）

**Files:**
- Create: `test/run_v1_baseline.py`

- [ ] **Step 1: 写脚本**

```python
"""跑 v1 agent 拿基线数据"""
import json
import requests
import time
from pathlib import Path

V1_URL = "http://localhost:8000/agent/chat"
CASES_PATH = Path(__file__).parent / "agent_test_cases.json"
OUTPUT_PATH = Path(__file__).parent / "v1_baseline_results.json"


def run_v1_case(case: dict) -> dict:
    """跑 1 个 case 记结果"""
    start = time.time()
    try:
        resp = requests.post(
            V1_URL,
            json={"query": case["query"], "session_id": f"v1_baseline_{case['id']}"},
            timeout=180
        )
        elapsed = time.time() - start
        data = resp.json()

        tool_chosen = data.get("tool_used", "unknown").split(" ")[0]  # 处理 "chat (降级)" 这种情况
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": tool_chosen,
            "is_correct": tool_chosen == case["expected_tool"],
            "response_time": round(elapsed, 2),
            "iterations": data.get("iterations", 0),
            "response_preview": data.get("response", "")[:200]
        }
    except Exception as e:
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": "ERROR",
            "is_correct": False,
            "error": str(e),
            "response_time": round(time.time() - start, 2)
        }


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    print(f"Running v1 baseline on {len(cases)} cases...")
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['query'][:30]}...")
        result = run_v1_case(case)
        results.append(result)
        status = "✓" if result["is_correct"] else "✗"
        print(f"  {status} chose {result['tool_chosen']} (expected {result['expected_tool']}) in {result['response_time']}s")

    # 统计
    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    avg_time = sum(r["response_time"] for r in results) / total

    summary = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3),
        "avg_response_time": round(avg_time, 2),
        "results": results
    }

    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== v1 Baseline ===")
    print(f"Accuracy: {correct}/{total} = {summary['accuracy']*100}%")
    print(f"Avg response time: {summary['avg_response_time']}s")
    print(f"Results saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本能 import**

Run: `cd D:/PythonProject/ragmi && python -c "import test.run_v1_baseline"`
Expected: 没有错误输出

- [ ] **Step 3: Commit**

```bash
git add test/run_v1_baseline.py
git commit -m "test: add v1 baseline eval script"
```

---

#### Task 4: 跑 v1 baseline（30 分钟 + 运行时间）

**Files:**
- Read: `test/v1_baseline_results.json` (auto-generated)

- [ ] **Step 1: 启动 v1 后端**

在终端 1 运行：
```bash
cd D:/PythonProject/ragmi && python main.py
```

Wait until: "Uvicorn running on http://127.0.0.1:8000"

- [ ] **Step 2: 在终端 2 跑 baseline**

```bash
cd D:/PythonProject/ragmi && python test/run_v1_baseline.py
```

Expected: 输出 "Accuracy: X/12 = Y%" 的统计

- [ ] **Step 3: 看哪些 case 选错**

Read `test/v1_baseline_results.json`，找出 `is_correct: false` 的 case ID，**重点关注 T04（"我的知识库有什么"）**。把 v1 选错的 case 记在 `docs/note/note_day1_react.md` 末尾。

- [ ] **Step 4: Commit**

```bash
git add test/v1_baseline_results.json docs/note/note_day1_react.md
git commit -m "test: v1 baseline results - X/12 cases correct"
```

---

### Phase 2: 搭骨架（Day 2）—— 5 个任务

#### Task 5: 安装 LangGraph + 创建目录（10 分钟）

- [ ] **Step 1: 装依赖**

```bash
cd D:/PythonProject/ragmi && pip install langgraph
```

Expected: Successfully installed langgraph-X.X.X

- [ ] **Step 2: 验证 import**

```bash
python -c "from langgraph.graph import StateGraph, START, END; from langgraph.prebuilt import ToolNode; from langgraph.checkpoint.memory import MemorySaver; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 建目录结构**

```bash
mkdir -p agent_v2/nodes agent_v2/tools agent_v2/prompts
```

- [ ] **Step 4: 写空的 `__init__.py`**

Create `agent_v2/__init__.py`:
```python
"""Agent v2 - LangGraph 实现"""
__version__ = "0.1.0"
```

Create `agent_v2/nodes/__init__.py`:
```python
```

Create `agent_v2/tools/__init__.py`:
```python
```

Create `agent_v2/prompts/__init__.py`:
```python
```

- [ ] **Step 5: 验证 import**

```bash
python -c "from agent_v2 import __version__; print(__version__)"
```

Expected: `0.1.0`

- [ ] **Step 6: Commit**

```bash
git add agent_v2/ requirements.txt
git commit -m "feat: scaffold agent_v2 directory structure"
```

---

#### Task 6: 定义 State（20 分钟）

**Files:**
- Create: `agent_v2/state.py`

- [ ] **Step 1: 写 state 定义**

```python
"""Agent v2 全局状态定义"""
from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """Agent 状态 schema

    - messages: 对话历史，框架自动追加（add_messages reducer）
    - tool_iterations: 已迭代次数
    - final_answer: 最终回答（None = 还没出）
    """
    messages: Annotated[list[BaseMessage], add_messages]
    tool_iterations: int
    final_answer: Optional[str]
```

- [ ] **Step 2: 验证能 import**

```bash
python -c "from agent_v2.state import AgentState; print(AgentState.__annotations__.keys())"
```

Expected: `dict_keys(['messages', 'tool_iterations', 'final_answer'])`

- [ ] **Step 3: Commit**

```bash
git add agent_v2/state.py
git commit -m "feat(agent_v2): define AgentState TypedDict"
```

---

#### Task 7: 写 Pydantic schemas（20 分钟）

**Files:**
- Create: `agent_v2/tools/schemas.py`

- [ ] **Step 1: 写 schema**

```python
"""RAG 工具的输入输出 schema"""
from pydantic import BaseModel, Field
from typing import List


class Source(BaseModel):
    """单个文档来源"""
    file: str = Field(..., description="来源文件名")
    chunk: str = Field(..., description="文档片段内容（前 200 字）")
    score: float = Field(..., description="相似度分数 0-1")


class RagResult(BaseModel):
    """RAG 工具返回结果"""
    answer: str = Field(..., description="基于检索内容生成的回答")
    sources: List[Source] = Field(default_factory=list, description="参考来源列表")
    is_empty: bool = Field(False, description="知识库是否为空（检索无结果）")
```

- [ ] **Step 2: 验证 schema**

```bash
python -c "from agent_v2.tools.schemas import Source, RagResult; r = RagResult(answer='test', sources=[Source(file='a.pdf', chunk='chunk content', score=0.9)]); print(r.model_dump_json())"
```

Expected: 输出 JSON 字符串

- [ ] **Step 3: Commit**

```bash
git add agent_v2/tools/schemas.py
git commit -m "feat(agent_v2): add Pydantic schemas for RAG tool I/O"
```

---

#### Task 8: 写系统提示词（20 分钟）

**Files:**
- Create: `agent_v2/prompts/system_prompt.py`

- [ ] **Step 1: 写提示词**

```python
"""Agent v2 系统提示词"""

SYSTEM_PROMPT = """你是一个智能助手，能够使用工具回答用户问题。

## 你有的工具

- `rag_search`: 检索用户的个人知识库。
  - **何时调用**：用户问题涉及用户自己的文档、笔记、上传的资料时
  - **何时不调用**：通用知识问题、闲聊、计算等

## 回答规则

1. 如果用户问"我的知识库有什么"、"我上传的文档讲了什么"等**涉及本地资料**的问题 → 必须调用 `rag_search` 工具
2. 如果是通用知识问题（"Python 是什么"、"北京天气"等）→ 直接回答，**不要调工具**
3. 如果不确定是否需要检索 → 调用 `rag_search`，宁可查多不要漏

## 输出格式

- 需要调工具时，框架会自动处理（你不需要自己输出 JSON）
- 不需要调工具时，直接用自然语言回答用户
"""
```

- [ ] **Step 2: 验证能 import**

```bash
python -c "from agent_v2.prompts.system_prompt import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT), 'chars')"
```

Expected: 输出字符数（大概 400-500）

- [ ] **Step 3: Commit**

```bash
git add agent_v2/prompts/system_prompt.py
git commit -m "feat(agent_v2): add system prompt with tool selection guidance"
```

---

#### Task 9: 写 RAG 工具（30 分钟）

**Files:**
- Create: `agent_v2/tools/rag_search.py`

- [ ] **Step 1: 写工具函数**

```python
"""RAG 检索工具 - 用 @tool 装饰"""
from typing import Optional
from langchain_core.tools import tool
from agent_v2.tools.schemas import Source, RagResult
from core.rags.rags import RagModel
from utils.models.model_manager import ModelManager
from utils.message.message import MessageManager


# 全局单例（v1 也有，保留）
_model_manager = None
_rag_model = None


def _get_rag_model() -> RagModel:
    global _model_manager, _rag_model
    if _rag_model is None:
        _model_manager = ModelManager()
        _model_manager.load_config_models()
        from utils.models.model_setting import LLMmodel
        default_model = LLMmodel.create_aliyun()  # 用阿里云
        _model_manager.set_current_model(default_model)
        _rag_model = RagModel(_model_manager)
    return _rag_model


@tool
def rag_search(query: str, top_k: int = 5, doc_type: Optional[str] = None) -> dict:
    """从用户的个人知识库检索相关内容。

    适用场景：
    - 用户问题涉及自己的文档、上传的资料、笔记
    - 用户问"我的知识库有什么"、"我上传的 X 讲了什么"
    - 需要引用已有材料回答

    Args:
        query: 检索关键词或问题
        top_k: 返回文档片段数量，默认 5
        doc_type: 限定文档类型（pdf/md/txt），None 表示不限

    Returns:
        dict: 包含 answer (str)、sources (list)、is_empty (bool)
    """
    try:
        rag = _get_rag_model()
        # 调 v1 的 RAG pipeline
        result = rag.chat(query=query, session_id=None)

        # v1 的 RAG 返回 dict，从 response 字段提取
        response_text = result.get("response", "")

        # 简化：v1 的 RAG 没返回结构化 sources，临时构造空列表
        # v3 改进：让 RagModel 返回 sources
        return RagResult(
            answer=response_text,
            sources=[],  # v1 暂时无法溯源
            is_empty=("没有找到相关文档片段" in response_text or "未找到" in response_text)
        ).model_dump()
    except Exception as e:
        return RagResult(
            answer=f"RAG 检索失败：{str(e)}",
            sources=[],
            is_empty=True
        ).model_dump()
```

- [ ] **Step 2: 验证工具能被 LangChain 解析**

```bash
python -c "from agent_v2.tools.rag_search import rag_search; print('name:', rag_search.name); print('desc:', rag_search.description[:100])"
```

Expected: 输出工具名和描述前 100 字

- [ ] **Step 3: Commit**

```bash
git add agent_v2/tools/rag_search.py
git commit -m "feat(agent_v2): add rag_search @tool with structured params"
```

---

### Phase 3: 写节点 + 装配图（Day 3）—— 4 个任务

#### Task 10: 写 agent_node（20 分钟）

**Files:**
- Create: `agent_v2/nodes/agent_node.py`

- [ ] **Step 1: 写节点函数**

```python
"""LLM 决策节点：调 LLM 决定下一步"""
from langchain_core.messages import SystemMessage
from agent_v2.state import AgentState
from agent_v2.prompts.system_prompt import SYSTEM_PROMPT
from agent_v2.tools.rag_search import rag_search
from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel


# 全局单例
_llm_with_tools = None


def _get_llm_with_tools():
    """获取绑定了 tools 的 LLM"""
    global _llm_with_tools
    if _llm_with_tools is None:
        # 用 v1 的 model_manager 方式
        mm = ModelManager()
        mm.load_config_models()
        default_model = LLMmodel.create_aliyun()
        mm.set_current_model(default_model)

        # 拿 LangChain 的 chat 对象，绑定 tools
        chat = default_model.chat.bind_tools([rag_search])
        _llm_with_tools = chat
    return _llm_with_tools


def agent_node(state: AgentState) -> dict:
    """LLM 决策节点

    输入：state（包含 messages）
    输出：{"messages": [AIMessage]}

    AIMessage 可能包含：
    - tool_calls: LLM 决定调工具
    - content: LLM 直接回答
    """
    messages = state["messages"]

    # 如果第一条不是 SystemMessage，注入 system prompt
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages

    llm = _get_llm_with_tools()
    response = llm.invoke(messages)

    return {"messages": [response]}
```

- [ ] **Step 2: 验证能 import**

```bash
python -c "from agent_v2.nodes.agent_node import agent_node; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agent_v2/nodes/agent_node.py
git commit -m "feat(agent_v2): add agent_node with bind_tools"
```

---

#### Task 11: 写 should_continue 条件边（15 分钟）

**Files:**
- Create: `agent_v2/nodes/should_continue.py`

- [ ] **Step 1: 写条件边函数**

```python
"""条件边：决定下一步走向"""
from agent_v2.state import AgentState


def should_continue(state: AgentState) -> str:
    """根据最后一条消息决定下一步

    Returns:
        "tools" - 继续执行工具
        "end"   - 结束
    """
    last_message = state["messages"][-1]

    # LLM 没调用工具 → 它决定直接回答 → 结束
    # AIMessage 有 tool_calls 属性（list，可能为空）
    if not getattr(last_message, "tool_calls", None):
        return "end"

    # 已迭代 3 次 → 强制结束（防止死循环）
    if state.get("tool_iterations", 0) >= 3:
        return "end"

    # 否则执行工具
    return "tools"
```

- [ ] **Step 2: 验证能 import**

```bash
python -c "from agent_v2.nodes.should_continue import should_continue; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agent_v2/nodes/should_continue.py
git commit -m "feat(agent_v2): add should_continue conditional edge"
```

---

#### Task 12: 装配 StateGraph（30 分钟）

**Files:**
- Create: `agent_v2/graph.py`

- [ ] **Step 1: 写 graph 装配**

```python
"""StateGraph 装配"""
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from agent_v2.state import AgentState
from agent_v2.nodes.agent_node import agent_node
from agent_v2.nodes.should_continue import should_continue
from agent_v2.tools.rag_search import rag_search


def build_graph():
    """构建 StateGraph"""
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools=[rag_search]))

    # 添加边
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )
    workflow.add_edge("tools", "agent")  # 工具执行完回到 LLM 决策

    # 编译（带内存 checkpoint）
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# 导出单例
compiled_graph = build_graph()
```

- [ ] **Step 2: 验证能 import + 画图**

```bash
python -c "from agent_v2.graph import compiled_graph; print('graph compiled'); print(compiled_graph.get_graph().draw_mermaid())"
```

Expected: 输出 Mermaid 图代码（应该看到 START → agent → 条件边 → {tools, END} → ...）

- [ ] **Step 3: 写 graph 截图到文档**

把 Mermaid 代码贴到 `docs/note/v2_graph_diagram.md`，加注释解释每个节点和边。

- [ ] **Step 4: Commit**

```bash
git add agent_v2/graph.py docs/note/v2_graph_diagram.md
git commit -m "feat(agent_v2): assemble StateGraph with conditional edges"
```

---

#### Task 13: 写 runtime（20 分钟）

**Files:**
- Create: `agent_v2/runtime.py`

- [ ] **Step 1: 写 runtime 入口**

```python
"""Agent v2 运行时入口 - 给 API 调用"""
from typing import Optional
from langchain_core.messages import HumanMessage, AIMessage

from agent_v2.graph import compiled_graph
from agent_v2.state import AgentState


def run(query: str, session_id: str, max_iterations: int = 3) -> dict:
    """运行 Agent v2

    Args:
        query: 用户问题
        session_id: 会话 ID（作为 thread_id）
        max_iterations: 最大迭代次数（这里只是占位，实际由 should_continue 控制）

    Returns:
        {
            "response": str,
            "session_id": str,
            "tool_used": str | None,
            "iterations": int,
            "sources": list
        }
    """
    config = {"configurable": {"thread_id": session_id}}
    initial_state: AgentState = {
        "messages": [HumanMessage(content=query)],
        "tool_iterations": 0,
        "final_answer": None
    }

    result = compiled_graph.invoke(initial_state, config=config)

    # 提取最终回答
    final_message = result["messages"][-1]
    response_text = final_message.content if isinstance(final_message, AIMessage) else str(final_message)

    # 提取 tool_used（从 messages 里找 ToolMessage）
    tool_used = None
    sources = []
    for msg in result["messages"]:
        # AIMessage 的 tool_calls 记录了调用的工具
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_used = tc["name"]
        # ToolMessage 记录了工具结果
        if msg.__class__.__name__ == "ToolMessage":
            # 尝试从 content 里提取 sources（简化处理）
            pass

    iterations = sum(1 for msg in result["messages"] if isinstance(msg, AIMessage) and msg.tool_calls)

    return {
        "response": response_text,
        "session_id": session_id,
        "tool_used": tool_used,
        "iterations": iterations,
        "sources": sources
    }
```

- [ ] **Step 2: 验证能 import**

```bash
python -c "from agent_v2.runtime import run; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agent_v2/runtime.py
git commit -m "feat(agent_v2): add runtime API entry point"
```

---

### Phase 4: API + 端到端测试（Day 4）—— 4 个任务

#### Task 14: 写 v2 API 路由（20 分钟）

**Files:**
- Create: `api/api_agent_v2.py`

- [ ] **Step 1: 写 API 路由**

```python
"""Agent v2 API 路由"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from .dependencies import get_model_manager
from agent_v2.runtime import run

appagent_v2 = APIRouter()


class AgentV2Request(BaseModel):
    query: str = Field(..., description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID")


class AgentV2Response(BaseModel):
    response: str
    session_id: str
    tool_used: Optional[str] = None
    iterations: int = 0
    sources: list = Field(default_factory=list)


@appagent_v2.post("/agent/v2/chat", response_model=AgentV2Response)
async def agent_v2_chat(request: AgentV2Request) -> AgentV2Response:
    """Agent v2 智能对话接口（LangGraph 版）"""
    import uuid
    session_id = request.session_id or str(uuid.uuid4())

    result = run(
        query=request.query,
        session_id=session_id,
    )

    return AgentV2Response(**result)
```

- [ ] **Step 2: 注册路由到 main.py**

Modify `main.py`：

找到 `from api.api_agent import appagent` 这一行（约第 10 行），在它下面加：
```python
from api.api_agent_v2 import appagent_v2
```

找到 `app.include_router(appagent, tags=["agent"])` 这一行（约第 28 行），在它下面加：
```python
app.include_router(appagent_v2, tags=["agent-v2"])
```

- [ ] **Step 3: Commit**

```bash
git add api/api_agent_v2.py main.py
git commit -m "feat(api): register /agent/v2/chat route"
```

---

#### Task 15: 端到端冒烟测试（30 分钟）

**Files:** Test manually with curl

- [ ] **Step 1: 启动 v2 后端**

```bash
cd D:/PythonProject/ragmi && python main.py
```

Wait until: "Uvicorn running on http://127.0.0.1:8000"

- [ ] **Step 2: 测最简单的 case**

```bash
curl -X POST http://localhost:8000/agent/v2/chat -H "Content-Type: application/json" -d "{\"query\": \"你好\", \"session_id\": \"smoke_test_1\"}"
```

Expected: 返回 `{"response": "...", "tool_used": null, "iterations": 0, ...}` （不需要调工具）

- [ ] **Step 3: 测"该用 RAG"的 case**

```bash
curl -X POST http://localhost:8000/agent/v2/chat -H "Content-Type: application/json" -d "{\"query\": \"在我的知识库里有什么内容\", \"session_id\": \"smoke_test_2\"}"
```

Expected: 返回 `{"response": "...", "tool_used": "rag_search", "iterations": 1, ...}` （关键！必须选对 RAG）

- [ ] **Step 4: 如果 case 2 选错**

进入 debug 模式：
- 看 system prompt 里"必须调用 rag_search"的指引够不够强
- 看 LLM 是不是不支持 tool_calls（**改用阿里云 qwen3.5-plus**）
- 看 ToolNode 有没有正确注册工具

- [ ] **Step 5: Commit 测试结果**

把两个 case 的响应 JSON 贴到 `docs/note/v2_smoke_test.md`，标注 PASS/FAIL。

```bash
git add docs/note/v2_smoke_test.md
git commit -m "test: v2 smoke test - PASS on case 1, PASS/FAIL on case 2"
```

---

#### Task 16: 写 v2 评估脚本（30 分钟）

**Files:**
- Create: `test/run_v2_eval.py`

- [ ] **Step 1: 写脚本**

```python
"""跑 v2 agent 拿评估数据"""
import json
import requests
import time
from pathlib import Path

V2_URL = "http://localhost:8000/agent/v2/chat"
CASES_PATH = Path(__file__).parent / "agent_test_cases.json"
OUTPUT_PATH = Path(__file__).parent / "v2_eval_results.json"


def run_v2_case(case: dict) -> dict:
    """跑 1 个 case 记结果"""
    start = time.time()
    try:
        resp = requests.post(
            V2_URL,
            json={"query": case["query"], "session_id": f"v2_eval_{case['id']}"},
            timeout=180
        )
        elapsed = time.time() - start
        data = resp.json()

        tool_chosen = data.get("tool_used") or "chat"  # None = 没调工具 = chat
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": tool_chosen,
            "is_correct": tool_chosen == case["expected_tool"],
            "response_time": round(elapsed, 2),
            "iterations": data.get("iterations", 0),
            "response_preview": data.get("response", "")[:200]
        }
    except Exception as e:
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": "ERROR",
            "is_correct": False,
            "error": str(e),
            "response_time": round(time.time() - start, 2)
        }


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    print(f"Running v2 eval on {len(cases)} cases...")
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['query'][:30]}...")
        result = run_v2_case(case)
        results.append(result)
        status = "✓" if result["is_correct"] else "✗"
        print(f"  {status} chose {result['tool_chosen']} (expected {case['expected_tool']}) in {result['response_time']}s")

    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    avg_time = sum(r["response_time"] for r in results) / total

    summary = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3),
        "avg_response_time": round(avg_time, 2),
        "results": results
    }

    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== v2 Results ===")
    print(f"Accuracy: {correct}/{total} = {summary['accuracy']*100}%")
    print(f"Avg response time: {summary['avg_response_time']}s")
    print(f"Results saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证能 import**

```bash
python -c "import test.run_v2_eval"
```

Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add test/run_v2_eval.py
git commit -m "test: add v2 eval script"
```

---

#### Task 17: 跑 v2 完整评估（30 分钟 + 运行时间）

- [ ] **Step 1: 确保 v2 后端在跑**

如果没在跑：
```bash
cd D:/PythonProject/ragmi && python main.py
```

- [ ] **Step 2: 跑 v2 评估**

```bash
cd D:/PythonProject/ragmi && python test/run_v2_eval.py
```

Expected: 输出 12 个 case 的结果和总 accuracy

- [ ] **Step 3: 如果 accuracy < 75%**

**停下来**。不要硬跑下一个任务。debug 半天：
- 看哪些 case 选错
- 检查 system prompt 是否需要加强
- 检查 LLM 是否真的支持 tool_calls

- [ ] **Step 4: Commit 结果**

```bash
git add test/v2_eval_results.json
git commit -m "test: v2 eval results - Y/12 cases correct (XX% accuracy)"
```

---

### Phase 5: 写对比 + 面试材料（Day 5）—— 3 个任务

#### Task 18: 写 v1 vs v2 对比报告（30 分钟）

**Files:**
- Create: `docs/anlaysis/v1_vs_v2.md`

- [ ] **Step 1: 写对比报告**

```markdown
# v1 vs v2 对比报告

> **写于 2026-07-XX**
> 基于 12 个测试 case 跑分

## 选对工具率

| 指标 | v1 | v2 | 改进 |
|---|---|---|---|
| 选对工具率 | X/12 (XX%) | Y/12 (YY%) | +ZZ% |
| 平均响应时间 | Xs | Ys | -Zs |
| 3 轮反思失败 case | N | M | -N |

## 选错 case 详细对比

| Case ID | 问题 | v1 选 | v2 选 | 期望 | 备注 |
|---|---|---|---|---|---|
| T01 | 你是谁 | chat | chat | chat | ✓ 都对 |
| T04 | 我的知识库有什么 | chat | rag_search | rag | v1 失败，v2 修复 |

## 面试核心数据

> "我用 LangGraph 重写了 Agent 控制器。在 12 个测试 case 上：
> - 选对工具率从 X% 提升到 Y%
> - 工具支持结构化参数（top_k、filter）
> - 用 LangGraph 内置超时替代了原来的 threading.Thread 泄漏
> - 代码量从 800 行降到 250 行"
```

- [ ] **Step 2: 填实际数据**

把 v1_baseline_results.json 和 v2_eval_results.json 的实际数字填进去。

- [ ] **Step 3: Commit**

```bash
git add docs/anlaysis/v1_vs_v2.md
git commit -m "docs: v1 vs v2 comparison report with eval data"
```

---

#### Task 19: 写面试 Q&A（45 分钟）

**Files:**
- Create: `docs/note/interview_QA.md`

- [ ] **Step 1: 写 8 个高频问题**

参考 `agent_note_03_react_deep_dive.md` §六的 3 段话术，**扩展到 8 个问题**：

1. 你的 Agent 怎么选工具的？
2. 什么是 ReAct 模式？你的项目怎么用？
3. v1 烂在哪？v2 怎么修？
4. 什么是 bind_tools？
5. 为什么用 LangGraph？vs LangChain AgentExecutor？
6. 你的 StateGraph 长什么样？画一下。
7. 工具怎么设计？
8. 你的项目怎么评估好坏？

每个问题配 100-200 字回答。

- [ ] **Step 2: Commit**

```bash
git add docs/note/interview_QA.md
git commit -m "docs: interview Q&A with 8 high-frequency questions"
```

---

#### Task 20: 收尾 commit（15 分钟）

- [ ] **Step 1: 检查所有文件都 commit 了**

```bash
git status
```

Expected: 干净的工作区（nothing to commit）

- [ ] **Step 2: 写 1 周复盘**

Create `docs/note/week1_v2_rewrite.md` (500 字)：
- 完成了什么
- 卡在哪里最久
- v2 还差什么

- [ ] **Step 3: 最终 commit**

```bash
git add docs/note/week1_v2_rewrite.md
git commit -m "docs: week 1 v2 rewrite retrospective"
```

---

## 三、Spec 覆盖检查

| 需求 | 对应任务 |
|---|---|
| 用 LangGraph 重写 | Task 5, 12 |
| 用 @tool 装饰器 | Task 9 |
| 用 bind_tools() | Task 10 |
| 保留 v1 代码 | 不动 agent/ 目录 |
| 跑通 /agent/v2/chat | Task 14, 15 |
| 12 case 测试集 | Task 2 |
| v1 baseline | Task 3, 4 |
| v2 评估 | Task 16, 17 |
| 对比报告 | Task 18 |
| 面试材料 | Task 19 |

**全覆盖**。

---

## 四、风险与回退

| 风险 | 应对 |
|---|---|
| LangGraph API 跟我训练数据里不一样 | 查官方文档 https://langchain-ai.github.io/langgraph/ |
| LLM 不支持 tool_calls | 改用阿里云 qwen3.5-plus（已写好） |
| 测试集 T04 选错 | 加强 system prompt 加 hard rule |
| 12 case 没到 75% | 停 30 分钟 debug system prompt，不硬改代码 |
| RagModel.chat() 不接受某些参数 | 改 rag_search.py 里的调用方式 |

---

## 五、不在这次计划里（明确延后）

- ❌ 流式输出（v3）
- ❌ 多 Agent（v3）
- ❌ Human-in-the-loop（v3）
- ❌ RAG 端点优化（独立任务）
- ❌ 前端切换开关（v3）

---

# 文档元信息

- **写于**：2026-07-09
- **基于**：用户决策"直接重写不再深挖 v1"
- **作者**：Claude (writing-plans skill)
- **下一步**：用户选择执行方式

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAGMI is a personal knowledge base Q&A system using RAG (Retrieval-Augmented Generation) technology with an Agent framework. The system supports document upload, parsing, chunking, vectorization, and intelligent answering via LLM with ReAct agent pattern.

## Commands

### Running the Application

```bash
# Start FastAPI backend (port 8000)
python main.py

# Start Streamlit frontend (port 8501)
streamlit run main_web.py
```

### API Debug

```bash
# Check backend status
curl http://localhost:8000/debug/simple
```

## Architecture

### Layered Architecture

```
┌─────────────────────────────────────────────┐
│  Streamlit Frontend (main_web.py)           │
│  - Single chat interface (智能问答)           │
│  - Knowledge base management                  │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  FastAPI Backend (main.py, port 8000)       │
│  - /agent/chat - ReAct Agent endpoint       │
│  - /rag - Direct RAG endpoint                │
│  - /chat - Direct chat endpoint              │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Agent Layer (agent/)                       │
│  - AgentController: ReAct loop + orchestration│
│  - BaseTool: Abstract tool interface         │
│  - RagTool / ChatTool: Tool implementations │
│  - core/: reasoning, strategy, evaluation   │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Core Layer (core/)                         │
│  - RagModel: RAG pipeline                  │
│  - ChatModel: Direct chat                  │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Data Layer                                 │
│  - Milvus: Vector storage                  │
│  - MessageManager: Session history         │
└─────────────────────────────────────────────┘
```

### Agent Architecture (agent/)

```
agent/
├── controller.py          # 编排层：协调 core 和 tools，执行 ReAct 循环
├── core/                  # Agent 核心业务逻辑
│   ├── reasoning.py       # 推理状态管理、LLM 输出解析（JSON + 正则 fallback）
│   ├── strategy.py        # 工具调度、超时控制、重试、Fallback 降级
│   └── evaluation.py      # 结果质量评估、Self-Correction
├── tools/                # 工具实现
│   ├── rag_tool.py        # RAG Tool (Milvus retrieval + LLM)
│   └── chat_tool.py       # Chat Tool (direct LLM)
├── base/
│   └── tool.py           # BaseTool 抽象基类
└── react_prompt.py       # ReAct 提示词（含 JSON 版本）
```

### Key Modules

| Module | Purpose |
|--------|---------|
| `agent/controller.py` | ReAct 循环入口，协调 reasoning/strategy/evaluation |
| `agent/core/reasoning.py` | 解析 LLM 输出，JSON 优先 + 正则 fallback |
| `agent/core/strategy.py` | 超时控制(30s)、重试机制、Fallback 降级 |
| `agent/core/evaluation.py` | 结果质量评估，触发 Self-Correction |
| `agent/tools/rag_tool.py` | RAG as a Tool (Milvus retrieval + LLM) |
| `agent/tools/chat_tool.py` | Chat as a Tool (direct LLM) |
| `core/rags/rags.py` | RAG pipeline: embed → search → generate |
| `utils/models/model_setting.py` | LLM wrapper (ChatOpenAI), supports multiple platforms |

### Supported LLM Platforms

Configuration in `configs/model_config.yaml` and `.env`:
- **Ollama**: Local models (deepseek-r1, qwen3)
- **MiniMax**: Cloud API (`MINIMAX_BASE_URL`, `MINIMAX_API_KEY`)
- **阿里云**: Qianwen series (`ALIYUN_BASE_URL`, `ALIYUN_API_KEY`)

### Vector Database

- **Milvus** (via `pymilvus.MilvusClient`) with Docker volume persistence
- **Embedding**: `bge-large` via Ollama (1024 dimensions)
- Collection name configured in `configs/model_config.yaml` (default: `langchain`)

## ReAct Agent Pattern

The Agent implements ReAct (Reasoning + Acting):

```
Reasoning → Acting → Observation → Evaluation
    ↓           ↓           ↓           ↓
  LLM决定    执行Tool    获取结果    检查质量
  工具选择              (含超时)    (充分?继续循环)
```

**Tool Selection Flow**:
1. LLM returns JSON: `{"tool": "rag", "confidence": 0.9, "reasoning": "..."}`
2. `parse_tool_choice_json()` parses JSON
3. If JSON fails, falls back to regex patterns
4. If confidence < 0.5, defaults to "chat"

**Multi-round ReAct with Self-Correction**:
- Max 3 iterations
- If result insufficient, adds reflection context and continues
- RAG timeout → retry → fallback to Chat

## Important Notes

- The Agent is the **only** chat entry point (unified interface)
- RAG and Chat are both Tools that the Agent decides when to use
- Frontend has no mode selection - Agent automatically decides
- Agent selects "rag" tool when question needs knowledge base, "chat" otherwise

---

## Agent Ecosystem Context

This section provides background on the broader LLM Agent landscape that informs RAGMI's design decisions.

### Why 2023-2024 Became the Agent爆发元年

The period from late 2023 through 2024 marked a paradigm shift in how enterprises and developers approached LLM applications. Several converging factors drove this:

1. **Capability Threshold Crossed**: LLMs improved sufficiently to move beyond single-shot completions to multi-step reasoning and action execution. Poor long-term reasoning and decision-making had been the main obstacles for developing usable LLM agents, and advances in instruction following resolved many of these bottlenecks.

2. **Economics of Automation**: Organizations recognized that AI agents could automate knowledge work at scale - moving from "AI as a chatbot" to "AI as a digital colleague" that could use tools, browse the web, and complete multi-day tasks autonomously.

3. **Ecosystem Maturity**: Tool calling interfaces, vector databases, and orchestration frameworks matured to the point where production deployments became feasible.

### Major Platform Agent Products

The enterprise AI agent market consolidated around several key players:

| Platform | Product | Key Capability |
|----------|---------|----------------|
| **OpenAI** | GPTs / Agents API | GPT Store ecosystem, function calling, Operator autonomous web browsing |
| **Anthropic** | Claude Code, Claude Cowork | Multi-day scientific computing, test oracles, persistent memory, Model Context Protocol (MCP) integration |
| **Google** | Gemini Agent Builder, Antigravity | Multi-step task execution, enterprise integrations (Shopify, GitHub, Replit), IDE agent-first development platform |
| **Microsoft** | Foundry Agent Service, Copilot Agents | Enterprise-grade orchestration, Azure AI integration, multi-agent workflows with RBAC and observability |
| **Amazon** | Bedrock Agents | AWS ecosystem integration, managed agent runtime |

### Technical Stack Components

Modern AI agent systems share a common architectural stack:

**1. Tool Calling (Function Calling)**
The foundational capability that allows agents to interact with external systems. All major LLM providers now support structured tool definitions:
- OpenAI's function calling
- Anthropic's tool use (via Claude Code and MCP)
- Google's multi-tool support in Gemini 3

**2. Memory Management**
Agents require persistent context mechanisms:
- **Short-term**: Conversation history and intermediate reasoning traces
- **Long-term**: Learned preferences, project-specific instructions (e.g., CLAUDE.md files), retrieved context from vector stores
- **Working memory**: Ability to track state across multi-step tasks

**3. Planning and Reasoning**
The ReAct (Reasoning + Acting) pattern became a de facto standard, involving:
- Reasoning about which tool to use
- Acting by executing the tool
- Observing the result
- Reflecting on whether the outcome is sufficient

Research from AgentBench (ICLR 2024) identified that "top commercial LLMs present a strong ability of acting as agents in complex environments," while open-source models under 70B parameters show "significant disparity in performance."

### User Scenarios and Pain Points

Based on documented enterprise deployments, primary agent use cases include:

**High-Frequency Automation**
- Code review and issue triage
- Document processing and formatting
- Customer support escalation handling

**Knowledge Work Augmentation**
- Research synthesis across multiple sources
- Complex document drafting with context awareness
- Data analysis with multi-tool orchestration

**Pain Points Observed**
1. **Context length limitations**: Complex tasks exceed model context windows
2. **Reliability in long-horizon tasks**: Error accumulation across many steps
3. **Tool use consistency**: Different LLMs interpret tool schemas differently
4. **Evaluation difficulty**: Hard to measure "was the task actually completed correctly"

### Emerging Standards: MCP

The Model Context Protocol (MCP) emerged as a USB-C-like standard for AI tool integration. Key benefits:
- **Developer**: Reduces integration complexity - build once, deploy across Claude/ChatGPT/VS Code/Cursor
- **Ecosystem**: Creates a marketplace of MCP servers for data sources (Google Calendar, Notion, Slack) and tools (search, calculators, code execution)
- **Enterprise**: Enables secure connection to organizational data sources with per-key access control

RAGMI's tool architecture aligns with this pattern - a BaseTool interface that agents can invoke, with RagTool and ChatTool as concrete implementations.

### Academic Perspective and Future Predictions

Research communities identified agent systems as a central theme at major conferences (NeurIPS, ICML, ACL). Key findings:

1. **Training on code has ambivalent impacts** on different agent tasks - contrary to earlier assumptions about universal benefits
2. **Instruction following quality** is the primary differentiator for agent performance
3. **Multi-round alignment data** significantly improves agent reliability

The shift toward "agentic AI" represents moving from reactive text generation to proactive task completion. Organizations deploying agents report productivity gains but also note the need for new governance frameworks around agent autonomy, audit trails, and safety guardrails.

### References

- [AgentBench: Evaluating LLMs as Agents (ICLR 2024)](https://arxiv.org/abs/2308.03688)
- [Anthropic Research: Trustworthy AI Agents](https://www.anthropic.com/research)
- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [Microsoft Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/)
- [Google Gemini Agent Capabilities](https://deepmind.google/technologies/gemini/)
- [CrewAI Multi-Agent Framework](https://docs.crewai.com/)
# RAGMI - 基于大模型的知识库问答系统

[![GitHub stars](https://img.shields.io/github/stars/Foggy-liu/Ragmi)](https://github.com/Foggy-liu/Ragmi)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

RAGMI 是一个基于检索增强生成（RAG）技术的个人知识库问答系统。系统支持上传多种格式文档，自动解析、切分、向量化存储，并通过大模型结合检索结果生成高质量回答。同时支持纯对话模式和多模型切换，提供完整的前后端分离架构。

## 项目地址

**https://github.com/Foggy-liu/Ragmi**

---

## 功能特性

### 多模式对话

- **纯对话模式**：直接与大模型交互，支持多轮对话和历史管理
- **RAG 模式**：基于上传文档的知识库问答，检索增强生成
- Agent 自动判断——无需人工切换模式

### LangGraph ReAct Agent (v2.1)

- **LangGraph StateGraph**：agent / tools / reflect 三节点，agent → {tools, reflect, END}，reflect → {agent, END}
- **Self-Reflection 闭环**（LLM-as-judge）：每轮回答后调反思 LLM 评判质量，不充分时把 critique 作为上下文追加让 agent 重答（最多 1 次）
- **双计数器保护**：`iterations` (max 5) 控制 agent 总调用次数，`reflection_count` (max 1) 控制反思次数，超限强制兜底放行
- **3 层 JSON 解析容错**：`json.loads` → 正则提取 `{...}` → fail-safe 默认 insufficient
- **异常兜底**：`runtime.ask()` 包 `try/except`，LLM 调用失败/超时不会 500，返回结构化错误响应
- **Debug 元数据**：返回 `{answer, iterations, reflection_count, score, tool_called}` 用于评估和调试

### 多模型支持

- **本地模型**：Ollama（Llama3、Qwen、DeepSeek 等）
- **云端模型**：阿里云百炼（通义千问系列）、MiniMax
- 运行时动态切换，无需重启服务

### Milvus 向量检索

- 使用 Milvus 作为向量数据库（Docker 部署，不占本地内存）
- Embedding 模型：bge-large（1024 维向量）
- 相似度检索 + Top-K 召回，支持增量更新

### 智能文本切分

- 双阶段切分：LangChain 机械切分 + 智能拼接
- 小于 80 字符的片段自动向后合并至 300 字符上限
- 30 字符重叠窗口保留跨 chunk 上下文

---

## 技术架构

```
用户
  ↓  Streamlit 前端（8501）
FastAPI 后端（8000）
  ↓
LangGraph Agent（图编排）
  ├── agent 节点    (决策: rag vs chat)
  ├── tools 节点    (rag_search: Milvus 检索 → LLM 生成)
  └── reflect 节点  (LLM-as-judge: 评判答案质量)
  ↓
Milvus (19530) → bge-large → LLM
Ollama / 阿里云 / MiniMax
```

### 项目目录 (v2.1)

```
ragmi/
├── api/                  # FastAPI 接口层
│   ├── api_agent.py     # /agent/chat 入口
│   ├── api_chat.py      # 纯对话接口
│   ├── api_file.py      # 文件上传接口
│   ├── api_rag.py       # RAG 接口
│   └── dependencies.py  # 依赖注入
├── agent/                # Agent 核心（LangGraph）
│   ├── graph.py         # StateGraph 装配（agent/tools/reflect 三节点）
│   ├── runtime.py       # 统一入口 ask() + 异常兜底 + Debug 元数据
│   ├── state.py         # AgentState + MAX_ITERS=5 + MAX_REFL=1
│   ├── nodes/
│   │   ├── agent.py     # agent 节点（决策 + 综合）
│   │   ├── reflect.py   # 反思节点（LLM-as-judge + 3 层 JSON 容错）
│   │   └── should_continue.py  # 条件边路由
│   ├── tools/
│   │   └── rag_tool.py  # rag_search 工具（Milvus 检索 + LLM 生成）
│   └── prompts/
│       ├── system_prompt.py    # Agent 主提示词
│       └── reflect_prompt.py   # 反思评判提示词
├── core/
│   ├── chat/            # 纯对话业务
│   └── rags/            # RAG 业务（Milvus 检索 + bge-large）
├── utils/
│   ├── docs/           # 文档解析
│   ├── models/         # 模型管理（Ollama/阿里云/MiniMax）
│   ├── txt_spliter/    # 文本切分 + Milvus 索引构建
│   └── message/        # 会话管理
├── test/                # 评估与测试
│   ├── agent_test_cases.json   # 12 个评估 case (T01-T12)
│   ├── run_agent_eval.py       # 离线评估入口（agent_eval_results.json）
│   ├── test_reflect.py         # 反思节点单元测试
│   └── langsmith_*.py          # LangSmith 集成（setup/evaluators/eval）
├── configs/            # 配置文件
├── docs/superpowers/   # 设计文档 + 实施计划
├── docker-compose.yml  # Docker 部署
└── requirements.txt    # 依赖列表
```

---

## 快速开始

### 环境要求

- Python 3.11+
- Docker + Docker Compose
- 可选：Ollama（本地模型）

### 1. 启动 Milvus 向量数据库

```bash
docker-compose -f docker-compose-milvus.yml up -d
```

等待约 90 秒后验证：

```bash
curl http://localhost:9091/healthz
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API 密钥
```

关键配置项：
```bash
# 阿里云（通义千问）
ALIYUN_API_KEY=your_key
ALIYUN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# MiniMax
MINIMAX_API_KEY=your_key
MINIMAX_BASE_URL=https://api.minimax.com/v1

# Milvus
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
```

### 4. 向量化文档

```bash
cd utils/txt_spliter
python vector_main.py
```

### 5. 启动服务

```bash
# 终端1：FastAPI 后端
python main.py

# 终端2：Streamlit 前端
streamlit run main_web.py
```

打开 http://localhost:8501 即可使用。

---

## Docker 部署（推荐）

### 方式一：一键部署（同时启动 App + Milvus）

```bash
docker-compose up -d
```

### 方式二：分别启动

```bash
# 终端1：启动 Milvus
docker-compose -f docker-compose-milvus.yml up -d

# 终端2：启动 App
docker-compose up -d app
```

---

## 技术亮点

### Self-Reflection 闭环（v2.1）

LLM-as-judge 模式：每轮回答后调反思 LLM 评判 `is_sufficient` + `critique`，不通过时把 critique 作为 AIMessage 追加让 agent 重答。3 层 JSON 解析容错（`json.loads` → 正则提取 `{...}` → fail-safe 默认 insufficient），`_to_bool()` 处理 LLM 返回字符串 `'false'` 的情况。

### 双计数器兜底

`iterations` (max 5) 控制 agent 节点总调用次数，`reflection_count` (max 1) 控制反思节点调用次数。两个 reducer 都是 `Annotated[int, _increment]`，节点返回 1 即可自动累加。超限在 `should_continue` 和 `reflect_node` 短路强制放行，避免无限循环。

### LangSmith 离线评估

`test/langsmith_setup.py` 建 Dataset（12 个 case）→ `test/langsmith_evaluators.py` 提供两个 evaluator（`tool_choice_evaluator` + `answer_keyword_evaluator`）→ `test/langsmith_eval.py --prefix <name>` 上传实验。在 [smith.langchain.com](https://smith.langchain.com) 查看 trace + 评分。

### 超时控制 + 异常兜底

agent 节点 `.with_config({"timeout": 30})`；`runtime.ask()` 包 `try/except`，LLM 调用失败不会 500，统一返回结构化错误响应。Debug 模式返回 `{iterations, reflection_count, score, tool_called}` 用于评估和调试。

### 多模型统一封装

通过 YAML 配置 + `.env` 占位符替换，实现 Ollama（本地）/ MiniMax / 阿里云三平台统一接口。运行时 `switch_model()` 动态切换，参数优先级：自定义 > 模型默认 > 平台默认。

### 两阶段文本切分

先用 `RecursiveCharacterTextSplitter` 按 `\n\n|\n|。|；|，` 机械切分，再将小于 80 字符的小片段智能合并至 300 字符上限，避免语义碎片化。

---

## 评估结果

12 个 case 在 MiniMax-M3 + Milvus 实测：

| 指标 | v2 baseline | v2.1 (with Reflection) |
|------|-------------|------------------------|
| 总准确率 | 92% | 91.7% (持平) |
| RAG 类 | 80% | 80% (4/5) |
| Chat 类 | 100% | 100% (7/7) |
| 反思触发率 | 0 | 1 次/case (T09 触发 2 次) |
| 最大 iterations | 1 | 5 (T11 简历) |

**结论**：反思没提升准确率（T06 "RAG 的核心定义" 路由错误无法事后修复），但增加了可观测性（`iterations` + `reflection_count`）。

跑评估：

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py
PYTHONIOENCODING=utf-8 python test/langsmith_eval.py --prefix v2.1-reflection
```

---

## 运行测试

项目用 pytest + 自研 eval 脚本 + Makefile 入口管理测试：

```bash
# 单元测试 + mock 评估（不需要真实 LLM key）
make test

# 或分别跑
make test-unit      # 10 个 parse_reflection_json + reflect_node 用例
make test-mock      # 12 个 agent 用例，reflect 用 MockLLM，agent 仍用真实 LLM
make test-eval      # 真实 LLM 全量评估（需要 .env 配 API key）
make clean          # 清 __pycache__ + .pytest_cache
```

测试入口：

- `pytest test/test_reflect.py -v` — 纯逻辑单元（10 用例，< 2 秒）
- `python test/test_reflection_count.py` — MAX_REFL=1 边界行为（2 场景）
- `python test/run_agent_eval.py [--mock]` — agent 路由评估，输出 `test/agent_eval_results.json`

当前 mock 模式基线：**11/12 = 91.7% routing accuracy, 12/12 = 100% stability**
（T06 "RAG 的核心定义" 唯一错例，真实 LLM 判为通用概念问答而非"查我文档"）

---

## 后续规划

- [x] Milvus 向量库替换 ChromaDB
- [x] Docker 容器化部署
- [x] Self-Reflection 闭环
- [x] LangSmith 离线评估
- [ ] 工具路由优化（修 T06 "RAG 的核心定义" 类问题）
- [ ] Faithfulness 评估（检查 RAG 答案是否真的用了检索片段）
- [ ] v2.2 会话管理 / 多轮记忆
- [ ] 混合检索（向量 + BM25）
- [ ] 用户认证与权限管理
- [ ] 文档版本管理

---

## 许可证

MIT License
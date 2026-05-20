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

### ReAct Agent 核心

- 完整 ReAct 循环：Reasoning → Acting → Observation → Evaluation
- 最多 3 轮自纠正迭代（Self-Correction），回答不充分时自动重试
- 两阶段质量评估：规则匹配（FAIL_PATTERNS/SUCCESS_PATTERNS）快速门控 + LLM Reflection 深度评估
- JSON 结构化输出优先 + 三级 Regex Fallback 降级解析
- RAG 超时 30s → 自动降级到 ChatTool 的容错机制

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
Agent 控制器（ReAct 循环）
  ├── RAG Tool  →  Milvus 向量检索  →  LLM 生成
  └── Chat Tool  →  直接 LLM 生成
  ↓
Ollama / 阿里云 / MiniMax
```

### 项目目录

```
ragmi/
├── api/                  # FastAPI 接口层
│   ├── api_agent.py     # Agent 入口
│   ├── api_chat.py      # 纯对话接口
│   ├── api_file.py      # 文件上传接口
│   ├── api_rag.py       # RAG 接口
│   └── dependencies.py  # 依赖注入
├── agent/                # Agent 核心
│   ├── controller.py    # ReAct 循环入口
│   ├── react_prompt.py  # 提示词模板
│   ├── core/
│   │   ├── reasoning.py   # LLM 输出解析
│   │   ├── strategy.py    # 超时/重试/降级
│   │   └── evaluation.py  # 质量评估
│   └── tools/
│       ├── rag_tool.py   # RAG 工具
│       └── chat_tool.py  # Chat 工具
├── core/
│   ├── chat/            # 纯对话业务
│   └── rags/            # RAG 业务
├── utils/
│   ├── docs/           # 文档解析
│   ├── models/         # 模型管理
│   ├── txt_spliter/    # 文本切分
│   └── message/        # 会话管理
├── configs/            # 配置文件
├── txt/                # 原始文稿
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

### ReAct Agent + Self-Correction

Agent 实现完整的 ReAct 循环，通过两阶段质量评估（规则匹配 + LLM Reflection）判断回答是否充分，不充分时自动触发重试迭代。

### 超时控制 + 自动降级

RAG 操作涉及向量检索 + LLM 生成两个慢环节。通过 `threading.Thread` + `join(timeout)` 实现 30s 超时控制，超时时自动降级到 ChatTool 保证服务可用。

### 多模型统一封装

通过 YAML 配置 + `.env` 占位符替换，实现 Ollama（本地）/ MiniMax / 阿里云三平台统一接口。运行时 `switch_model()` 动态切换，参数优先级：自定义 > 模型默认 > 平台默认。

### 两阶段文本切分

先用 `RecursiveCharacterTextSplitter` 按 `\n\n|\n|。|；|，` 机械切分，再将小于 80 字符的小片段智能合并至 300 字符上限，避免语义碎片化。

---

## 后续规划

- [x] Milvus 向量库替换 ChromaDB
- [x] Docker 容器化部署
- [ ] RAG 效果评估体系
- [ ] 混合检索（向量 + BM25）
- [ ] 用户认证与权限管理
- [ ] 文档版本管理

---

## 许可证

MIT License
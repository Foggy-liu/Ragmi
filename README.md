# 个人知识库问答系统

## 项目简介

RAGMI 是一个基于检索增强生成（RAG）技术的个人知识库问答系统。系统支持上传多种格式文档，自动解析、切分、向量化存储，并通过大模型结合检索结果生成高质量回答。同时支持纯对话模式和多模型切换，提供完整的前后端分离架构。

## 技术架构

### 整体架构图

```
用户打开系统
        ↓
[交互层] Streamlit前端
├── 模式选择 → 文档上传（RAG模式） → 输入问题
        ↓
[接口层] FastAPI路由分发
├── 根据模式选择对应路由
        ↓
[业务层] 模式处理核心
├── 路由判断
        ├─────────────┐
        ↓             ↓
┌─────────────┐  ┌─────────────┐
│  纯Chat业务  │  │   RAG业务     │
│             │  │              │
│ 调用[工具层]  │  │ 调用[工具层]  │
│ 通用模型工具  │  │ 1. 文档解析工具│
│             │  │ 2. 文本切分工具│
│             │  │ 3. 向量检索工具│
│             │  │ 4. 通用模型工具│
└─────────────┘  └─────────────┘
        ↓             ↓
[数据层] 存储/读取      [数据层] 存储/读取
├── 历史记录          ├── 1. 向量库
                      ├── 2. 切分文本
                      └── 3. 原始文档
        ↓             ↓
   返回答案          返回增强答案
        ↓
[交互层] 前端展示结果
```

### 项目目录结构

```
ragmi/
├── .streamlit/           # Streamlit 配置文件
├── api/                  # FastAPI 接口层
│   ├── api_chat.py       # 纯对话接口
│   ├── api_file.py       # 文件上传接口
│   ├── api_model.py      # 模型切换接口
│   ├── api_rag.py        # RAG 问答接口
│   ├── api_vector.py     # 向量检索接口
│   └── dependencies.py   # 依赖注入
├── configs/              # 配置文件
│   └── model_config.yaml # 模型配置
├── core/                 # 核心业务层
│   ├── chat/             # 纯对话业务
│   └── rags/             # RAG 业务
├── data/                 # 向量数据库存储
├── documents/            # 原始文档
├── txt/                  # 解析后的文本
├── utils/                # 工具层
│   ├── docs/             # 文档解析工具
│   │   ├── manager/      # 扫描、过滤、输出管理
│   │   └── process/      # MD/Word/PDF 处理器
│   ├── message/          # 消息管理工具
│   ├── models/           # 模型管理工具
│   └── txt_spliter/      # 文本切分工具
├── web_page/             # Streamlit 前端页面
├── .env                  # 环境变量（含API密钥）
├── main.py               # FastAPI 入口
├── main_web.py           # Streamlit 入口
└── requirements.txt      # 依赖列表
```

## 核心功能

### 1. 多模式对话

- **纯对话模式**：直接与大模型交互，支持多轮对话和历史管理
- **RAG 模式**：基于上传文档的知识库问答，检索增强生成

### 2. 文档处理流程

```
文档上传 → 格式解析 → 文本清洗 → 智能切分 → 向量化 → 存储到 ChromaDB
```

支持的文档格式：
- PDF（.pdf）
- Word（.docx）
- Markdown（.md）
- 纯文本（.txt）

### 3. 多模型支持

通过统一配置管理，支持：
- **本地模型**：Ollama（Llama3、Qwen、DeepSeek 等）
- **云端模型**：阿里云百炼（通义千问系列）

模型切换无需修改代码，通过 API 动态切换。

### 4. 会话管理

- 基于 `session_id` 的会话隔离
- 自动维护对话历史
- 支持历史截断（保留最近20条消息）
- 一键清除对话历史

### 5. 向量检索

- 使用 ChromaDB 作为向量数据库
- Embedding 模型：bge-large（512 token 限制）
- 相似度检索 + Top-K 召回
- 支持增量更新

## 技术亮点

### 1. 分层架构设计

- **工具层**：文档解析、文本切分、模型管理、消息管理
- **业务层**：纯对话、RAG 问答
- **接口层**：FastAPI RESTful API
- **前端层**：Streamlit 交互界面

### 2. 模型管理设计

- 单例模式管理模型实例，避免重复创建
- 懒加载机制，按需创建
- 统一配置文件驱动，支持多平台切换

### 3. 文档解析优化

- 增量更新：基于 MD5 哈希 + 文件修改时间，避免重复处理
- 解耦设计：处理器注册机制，新增格式只需添加处理器
- 冲突解决：输出路径自动添加计数器

### 4. 文本切分优化

- 双阶段切分：LangChain 机械切分 + 智能拼接
- 语义优先：按段落、句子边界切分
- 自适应合并：动态合并过小片段

### 5. 依赖注入设计

- FastAPI 依赖注入实现模型管理器的全局共享
- 所有路由共享同一实例，避免重复初始化

## 快速开始

### 环境要求

- Python 3.11+
- 可选：Ollama（本地模型）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境变量

复制 `.env.example` 为 `.env`，填写配置：

```bash
# 阿里云配置
ALIYUN_API_KEY=your_api_key_here
ALIYUN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ALIYUN_MODEL_NAME=qwen-plus

# 项目根目录
LLM_ROOT=D:\\PythonProject\\ragmi
```

### 启动服务

**启动 FastAPI 后端：**

```bash
python main.py
```

**启动 Streamlit 前端：**

```bash
streamlit run main_web.py
```

### 使用流程

1. 打开 Streamlit 前端（默认 http://localhost:8501）
2. 选择对话模式（纯对话 / RAG 模式）
3. RAG 模式下先上传文档
4. 输入问题，获取回答
5. 支持切换模型、清除历史

## RAG 优化方向

### 索引优化

- **摘要索引**：为文档片段生成摘要，提升检索精度
- **假设性问题索引**：预生成可能问题，反推原始文档
- **元数据索引**：提取文档元数据辅助检索

### 查询优化

- 用户提问改写（纠错、语义扩展）
- 多轮对话上下文融合

### 检索优化

- 重排序（Re-ranking）
- 混合检索（向量 + 关键词）

## 后续规划

- [ ] 增加数据库持久化（PostgreSQL + Redis）
- [ ] 用户认证与权限管理
- [ ] 文档版本管理
- [ ] Docker 容器化部署

## 许可证

MIT License

---

**项目地址**：[https://github.com/Foggy-liu/Ragmi](https://github.com/Foggy-liu/Ragmi)
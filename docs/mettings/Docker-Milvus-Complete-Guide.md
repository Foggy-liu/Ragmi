# RAGMI Docker 部署与 Milvus 向量数据库完整指南

## 目录

```
第一部分：概念与架构
├── 1.1 Docker 核心概念（镜像 vs 容器）
├── 1.2 Dockerfile vs docker-compose.yml 的区别
└── 1.3 端口映射与网络原理

第二部分：项目架构
├── 2.1 RAGMI 项目中的服务分类
├── 2.2 服务间通信关系
└── 2.3 数据流向图

第三部分：Milvus 向量数据库
├── 3.1 Milvus 部署架构（3 容器模式）
├── 3.2 向量化数据存储位置
└── 3.3 Attu 可视化管理

第四部分：部署实战
├── 4.1 部署步骤正确顺序
├── 4.2 编写 Dockerfile
├── 4.3 编写 docker-compose.yml
└── 4.4 启动与验证

第五部分：运维命令
├── 5.1 常用 Docker 命令
├── 5.2 常见问题排查
└── 5.3 数据备份与恢复
```

---

# 第一部分：概念与架构

## 1.1 Docker 核心概念（镜像 vs 容器）

### 一句话解释

```
镜像（Image）= 模具（只读的模板，构建一次）
容器（Container）= 从模具做出来的蛋糕（运行中的实例）
```

### 比喻说明

```
你开蛋糕店：
- 模具（Image）= 制作蛋糕的图纸，可以反复使用
- 蛋糕（Container）= 用模具做出的实际产品

Milvus 例子：
- 镜像：milvusdb/milvus:v2.6.16（官方发布的安装包）
- 容器：milvus-standalone（从这个镜像启动的运行实例）
```

### 核心命令

```bash
# 查看本地镜像
docker images

# 查看运行中的容器
docker ps

# 从镜像启动容器
docker run -d --name my-milvus milvusdb/milvus:v2.6.16

# 停止/删除容器
docker stop my-milvus
docker rm my-milvus

# 删除镜像
docker rmi milvusdb/milvus:v2.6.16
```

---

## 1.2 Dockerfile vs docker-compose.yml 的区别

### 一句话解释

```
Dockerfile  = 菜谱（描述单个应用怎么构建成镜像）
docker-compose = 菜单（描述整个系统有哪些服务，怎么运行）
```

### 详细对比

```
┌────────────────────────────────────────────────────────────────┐
│                        Dockerfile                               │
│                                                                 │
│  问题：这个 Python 应用怎么打包成镜像？                          │
│                                                                 │
│  包含内容：                                                     │
│  - FROM python:3.11-slim     # 用什么基础操作系统               │
│  - COPY requirements.txt .   # 复制依赖文件                     │
│  - RUN pip install ...       # 安装依赖                        │
│  - COPY . .                  # 复制应用代码                     │
│  - EXPOSE 8000               # 声明端口                         │
│  - CMD ["python", "main.py"] # 启动命令                         │
│                                                                 │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    docker-compose.yml                          │
│                                                                 │
│  问题：这个系统需要哪些服务？怎么组织起来？                      │
│                                                                 │
│  包含内容：                                                     │
│  - services:                    # 有哪些服务                     │
│  - build: .                     # 用哪个 Dockerfile 构建         │
│  - ports: ["8000:8000"]        # 端口映射                       │
│  - environment: [...]          # 环境变量                      │
│  - depends_on: [milvus]        # 依赖关系                       │
│  - volumes: [...]               # 数据持久化                    │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### RAGMI 项目的实际文件

```
D:\PythonProject\ragmi\
├── Dockerfile              ← 定义如何构建 app 镜像
├── docker-compose.yml      ← 定义 app + milvus 如何一起运行
├── docker-compose-offline.yml  ← 单独 Milvus（官方推荐3容器）
└── docker-compose-milvus.yml   ← 单独 Milvus（独立容器）
```

---

## 1.3 端口映射与网络原理

### 端口映射类比

```
医院挂号柜台（外部）    →    内部诊室
     80                      8080

Docker 端口映射：
宿主机 :8501  →  映射到  →  容器内 :8501

就像：医院挂号窗口(外部80) → 内部诊室(8080)
```

### RAGMI 项目的端口映射

```
宿主机（你的电脑）                容器内部
───────────────────────────────────────────────────────
:8501  ──→ Streamlit 前端        :8501
:8000  ──→ FastAPI 后端           :8000
:19530 ──→ Milvus gRPC           :19530
:9091  ──→ Milvus 健康检查       :9091

容器间通信（用服务名，不是 localhost）：
app 容器 → milvus:19530  （不是 localhost:19530）
app 容器 → redis:6379    （如果加了 Redis）
```

### 网络隔离说明

```
Docker 创建的虚拟网络

┌──────────────────────────────────────────────────────────────┐
│                    内部网络（容器间通信）                       │
│                                                              │
│   ┌──────────┐       ┌──────────┐       ┌───────────┐       │
│   │  etcd    │ ←───  │  milvus  │ ←───  │   minio   │       │
│   │  :2379   │       │  :19530  │       │   :9000   │       │
│   └──────────┘       └──────────┘       └───────────┘       │
│                                                              │
│   这些端口：外部无法直接访问，仅限容器间通信                    │
│   只有 19530 和 9091 通过 ports 暴露给宿主机                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

# 第二部分：项目架构

## 2.1 RAGMI 项目中的服务分类

### 需要部署的服务（用 Docker）

```
┌────────────────────────────────────────────────────────────┐
│  服务          │  部署方式           │  端口                 │
├────────────────────────────────────────────────────────────┤
│  Milvus        │  官方镜像（3容器）   │  19530, 9091          │
│  FastAPI       │  Dockerfile 构建    │  8000                 │
│  Streamlit     │  合并到 app 容器     │  8501                 │
│  Redis         │  官方镜像（可选）    │  6379                 │
└────────────────────────────────────────────────────────────┘
```

### 不是服务的（直接 pip 安装的库）

```
┌────────────────────────────────────────────────────────────┐
│  库/程序        │  说明                                    │
├────────────────────────────────────────────────────────────┤
│  Langchain      │  Python 库，pip install                  │
│  Ollama         │  装在宿主机的独立程序，不是 Docker         │
│  LLM/Embedding  │  Ollama 提供的模型，通过 http 访问        │
└────────────────────────────────────────────────────────────┘

重要：Ollama 运行在宿主机上，通过 http://localhost:11434 访问
```

---

## 2.2 服务间通信关系

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户请求                                 │
│                            ↓                                    │
│              ┌─────────────────────────────┐                   │
│              │     Streamlit (8501)          │  ← 浏览器访问     │
│              └─────────────┬───────────────┘                   │
│                            ↓                                   │
│              ┌─────────────────────────────┐                   │
│              │     FastAPI (8000)           │  ← 后端 API       │
│              └─────────────┬───────────────┘                   │
│                            ↓                                   │
│              ┌─────────────────────────────┐                   │
│              │     Agent 控制器             │                   │
│              │  (ReAct 循环 + 工具选择)     │                   │
│              └─────────────┬───────────────┘                   │
│                            ↓                                   │
│              ┌─────────────┴───────────────┐                   │
│              ↓                               ↓                 │
│    ┌─────────────────┐           ┌─────────────────┐           │
│    │   RagTool       │           │   ChatTool      │           │
│    │   (RAG 搜索)     │           │   (直接对话)     │           │
│    └────────┬────────┘           └─────────────────┘           │
│             ↓                                               │
│    ┌─────────────────┐                                      │
│    │   Milvus        │  ← 搜索向量                          │
│    │   (19530)        │                                      │
│    └────────┬────────┘                                      │
│             ↓                                               │
│    ┌─────────────────┐                                      │
│    │   Ollama        │  ← 嵌入/生成（不在 Docker）           │
│    │   (localhost)   │                                      │
│    └─────────────────┘                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2.3 数据流向图

### 向量化存储流程（文档 → Milvus）

```
┌─────────────────────────────────────────────────────────────────┐
│  第一阶段：文档准备                                              │
└─────────────────────────────────────────────────────────────────┘

  txt/ 文件夹（原始文档）
       ↓
  Splitter 切分（约 300 字符一块）
       ↓
  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │ chunk1  │  │ chunk2  │  │ chunk3  │ ... 共 1429 个
  └─────────┘  └─────────┘  └─────────┘

┌─────────────────────────────────────────────────────────────────┐
│  第二阶段：向量化                                                │
└─────────────────────────────────────────────────────────────────┘

  每个 chunk
       ↓  Ollama bge-large (embed_query)
  ┌─────────────────────────────────┐
  │  [0.034, -0.021, 0.089, ...]    │  ← 1024 维向量
  │           1,429 个               │
  └─────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  第三阶段：存储到 Milvus                                         │
└─────────────────────────────────────────────────────────────────┘

  MilvusClient.insert()
       ↓
  ┌─────────────────────────────────────────┐
  │         Collection: txt_data             │
  │  ┌─────────────────────────────────┐    │
  │  │ id │ vector(1024) │ text        │    │
  │  ├─────────────────────────────────┤    │
  │  │ 1  │ [0.03..]    │ chunk1..    │    │
  │  │ 2  │ [0.05..]    │ chunk2..    │    │
  │  │... │ ...         │ ...         │    │
  │  └─────────────────────────────────┘    │
  │                                          │
  │  create_index() → AUTOINDEX (COSINE)     │
  │  load_collection()                       │
  └─────────────────────────────────────────┘

  完成！1429 个向量已存储
```

### 查询流程（用户提问 → 答案）

```
┌─────────────────────────────────────────────────────────────────┐
│  用户提问                                                        │
└─────────────────────────────────────────────────────────────────┘

  用户问："什么是 RAG？"
       ↓
  FastAPI 接收请求
       ↓
  Ollama embed_query("什么是 RAG？")
       ↓
  ┌─────────────────────────────┐
  │  [0.012, -0.034, 0.056, ...] │  ← 查询向量
  └─────────────────────────────┘
       ↓
  MilvusClient.search(data=[query_vector])
       ↓
  ┌─────────────────────────────────────────┐
  │  Milvus 内部：                           │
  │  1. 在 vector 字段上搜索                   │
  │  2. 计算余弦相似度                         │
  │  3. 返回最近的 K 个结果                    │
  └─────────────────────────────────────────┘
       ↓
  返回相关 chunk（文本内容）
       ↓
  构建上下文提示词 → LLM 生成回答
       ↓
  返回给用户
```

---

# 第三部分：Milvus 向量数据库

## 3.1 Milvus 部署架构（3 容器模式）

### 为什么需要 3 个容器？

```
┌─────────────────────────────────────────────────────────────────┐
│                        Milvus 架构                              │
│                                                                 │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐          │
│  │   etcd     │    │  milvus    │    │   minio    │          │
│  │ (元数据)    │ ←  │ (主服务)    │ →  │ (向量存储)  │          │
│  │  :2379     │    │  :19530    │    │  :9000     │          │
│  └────────────┘    └────────────┘    └────────────┘          │
│                                                                 │
│  etcd:     存储 Collection 的元数据（名称、schema、索引信息）   │
│  minio:    存储实际的向量数据（底层用 S3 协议）                  │
│  milvus:   处理 gRPC 请求，协调 etcd 和 minio                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 官方 docker-compose-offline.yml

```yaml
version: '3.5'

services:
  etcd:
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.25
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/etcd:/etcd
    command: etcd -advertise-client-urls=http://etcd:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    healthcheck:
      test: ["CMD", "etcdctl", "endpoint", "health"]
      interval: 30s
      timeout: 20s
      retries: 3

  minio:
    container_name: milvus-minio
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    ports:
      - "9001:9001"  # 管理界面
      - "9000:9000"  # S3 协议
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/minio:/minio_data
    command: minio server /minio_data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  standalone:
    container_name: milvus-standalone
    image: milvusdb/milvus:v2.6.16
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
    ports:
      - "19530:19530"  # gRPC 端口
      - "9091:9091"    # 健康检查端口
    depends_on:
      - "etcd"
      - "minio"
```

### 部署命令

```bash
# 第一次部署
docker-compose -f docker-compose-offline.yml up -d

# 验证
curl http://localhost:9091/healthz
# 返回: {"status":"OK"}

# 查看容器状态
docker ps
# 显示: milvus-etcd, milvus-minio, milvus-standalone
```

---

## 3.2 向量化数据存储位置

### 数据不在 data/ 文件夹

```
D:\PythonProject\ragmi\
├── data/
│   ├── chroma.sqlite3     ← 旧的 ChromaDB 数据（不再使用）
│   └── ...
│
├── volumes/               ← Milvus 数据在这里！
│   └── milvus/
│       └── data/          ← 映射到容器内 /var/lib/milvus
│
└── txt/                   ← 原始文档（源文件）
```

### 查看容器内数据

```bash
# 进入 Milvus 容器
docker exec -it milvus-standalone bash

# 查看数据目录
ls -la /var/lib/milvus

# 查看数据大小
du -sh /var/lib/milvus
```

### 验证数据存在（Python）

```python
from pymilvus import MilvusClient

client = MilvusClient(uri='http://127.0.0.1:19530')

# 查看所有集合
print('集合列表:', client.list_collections())

# 查看 txt_data 统计
stats = client.get_collection_stats('txt_data')
print(f"txt_data: {stats['row_count']} 条数据")
```

---

## 3.3 Attu 可视化管理

### Attu 安装

```bash
# 一条命令启动 Attu
docker run -d \
  --name attu \
  -p 3000:3000 \
  -e MILVUS_HOST=host.docker.internal \
  -e MILVUS_PORT=19530 \
  -e PORT=3000 \
  zilliz/attu:latest
```

### Attu 连接配置

```
Milvus 地址:  host.docker.internal:19530
用户名:       （留空）
密码:         （留空）
```

### Attu 功能

```
┌─────────────────────────────────────────────────────────────┐
│  Attu 能做什么                                              │
├─────────────────────────────────────────────────────────────┤
│  ✓ 查看所有 Collections                                     │
│  ✓ 查看数据条数                                             │
│  ✓ 查看字段结构                                              │
│  ✓ 测试向量搜索                                              │
│  ✓ 创建/删除 Collection                                      │
│  ✓ 导入数据                                                  │
│  ✓ 查看索引状态                                              │
└─────────────────────────────────────────────────────────────┘
```

---

# 第四部分：部署实战

## 4.1 部署步骤正确顺序

```
┌─────────────────────────────────────────────────────────────────┐
│                     正确的部署顺序                                │
│                                                                 │
│  第 0 步：先搞懂架构关系                                         │
│           ↓                                                     │
│           有哪些服务？服务之间怎么通信？                         │
│                                                                 │
│  第 1 步：搞懂端口关系                                          │
│           ↓                                                     │
│           哪些暴露给用户？哪些内部通信？                         │
│                                                                 │
│  第 2 步：写 Dockerfile                                         │
│           ↓                                                     │
│           你的 Python 应用怎么打包成镜像？                       │
│                                                                 │
│  第 3 步：写 docker-compose.yml                                 │
│           ↓                                                     │
│           所有服务怎么组织起来运行？                            │
│                                                                 │
│  第 4 步：测试验证                                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

错误顺序（会导致返工）：
❌ 先写 Dockerfile → 不知道服务怎么通信
❌ 先写 docker-compose → 不知道应用怎么构建
❌ 先配端口 → 不知道服务关系
```

---

## 4.2 编写 Dockerfile

### RAGMI 项目的 Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim                  # 第1步：基础镜像（操作系统 + Python）

WORKDIR /app                            # 第2步：工作目录

# 第3步：安装系统依赖（curl 用于健康检查）
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# 第4步：复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 第5步：复制应用代码
COPY . .

# 第6步：声明端口
EXPOSE 8000 8501

# 第7步：启动命令
CMD ["uvicorn", "api.api_file:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 关键指令解释

```
FROM python:3.11-slim
  → 使用 Python 3.11 的轻量级镜像作为基础

WORKDIR /app
  → 切换到 /app 目录，后续命令都在这里执行

COPY requirements.txt .
  → 复制依赖文件到当前目录（. 表示 WORKDIR）

RUN pip install -r requirements.txt
  → 安装 Python 依赖

COPY . .
  → 复制所有代码到镜像

EXPOSE 8000 8501
  → 声明需要暴露的端口（不会实际开放，只是文档）

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
  → 容器启动时执行的命令
```

---

## 4.3 编写 docker-compose.yml

### RAGMI 项目的 docker-compose.yml

```yaml
version: '3.8'

services:
  # ========== 你的应用 ==========
  app:
    build: .                            # 从当前目录的 Dockerfile 构建
    container_name: docker-ragmi-app     # 容器名称
    ports:
      - "8000:8000"                     # FastAPI 端口
      - "8501:8501"                     # Streamlit 端口
    environment:
      - LLM_ROOT=/app                   # 环境变量
      - MILVUS_HOST=host.docker.internal # 连接 Milvus（从容器内访问宿主机）
      - MILVUS_PORT=19530
    env_file:
      - .env                            # 环境变量文件
    volumes:
      - ./txt:/app/txt                  # 挂载原始文档目录
    network_mode: host                   # 使用宿主机网络（简化通信）
    depends_on:
      - milvus                           # 等 Milvus 启动后再启动

  # ========== Milvus（官方 3 容器模式） ==========
  milvus-etcd:
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.25
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/etcd:/etcd
    command: etcd -advertise-client-urls=http://etcd:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    healthcheck:
      test: ["CMD", "etcdctl", "endpoint", "health"]
      interval: 30s
      timeout: 20s
      retries: 3

  milvus-minio:
    container_name: milvus-minio
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    ports:
      - "9001:9001"
      - "9000:9000"
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/minio:/minio_data
    command: minio server /minio_data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  milvus:
    container_name: milvus-standalone
    image: milvusdb/milvus:v2.6.16
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
    ports:
      - "19530:19530"
      - "9091:9091"
    depends_on:
      - milvus-etcd
      - milvus-minio

volumes:
  milvus-data:
```

---

## 4.4 启动与验证

### 完整部署步骤

```bash
# ========== 第 1 步：确保 Docker 在运行 ==========
docker ps

# ========== 第 2 步：启动 Milvus ==========
docker-compose -f docker-compose-offline.yml up -d

# 等待 90 秒，然后验证
curl http://localhost:9091/healthz
# 返回: {"status":"OK"}

# ========== 第 3 步：向量化文档 ==========
cd D:\PythonProject\ragmi
set PYTHONPATH=.
python -m utils.txt_spliter.vector_main

# 看到: "Milvus 向量库创建成功！文档片段数: 1429"

# ========== 第 4 步：启动所有服务 ==========
docker-compose up -d --build

# ========== 第 5 步：验证 ==========
# 查看容器状态
docker ps

# 测试访问
# 浏览器打开:
#   http://localhost:8501  → Streamlit 前端
#   http://localhost:8000/docs → FastAPI 文档
```

### 验证命令汇总

```bash
# 查看运行状态
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 查看 Milvus 健康
curl http://localhost:9091/healthz

# 查看 Milvus 数据
python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://127.0.0.1:19530')
print('集合:', c.list_collections())
print('txt_data:', c.get_collection_stats('txt_data')['row_count'], '条')
"

# 查看 Attu（如果已安装）
curl -s http://localhost:3000/ | grep -o '<title>.*</title>'
```

---

# 第五部分：运维命令

## 5.1 常用 Docker 命令

```bash
# ========== 启动/停止 ==========
docker-compose up -d              # 启动所有服务
docker-compose down                # 停止所有服务（数据保留）
docker-compose down -v             # 停止并删除数据卷（清空数据）
docker-compose restart             # 重启所有服务
docker-compose restart app         # 重启某个服务

# ========== 构建/更新 ==========
docker-compose build              # 构建镜像（代码改了要重新构建）
docker-compose up -d --build      # 重新构建并启动

# ========== 查看状态 ==========
docker ps                          # 查看运行中的容器
docker ps -a                       # 查看所有容器（包括停止的）
docker logs -f <容器名>            # 实时查看日志
docker logs --tail 100 <容器名>     # 查看最近 100 行日志

# ========== 进入容器 ==========
docker exec -it <容器名> bash       # 进入容器内部
docker exec -it milvus-standalone bash

# ========== 清理 ==========
docker system prune               # 清理未使用的镜像/容器/网络
docker image prune                # 清理未使用的镜像
```

## 5.2 常见问题排查

### 问题 1：端口被占用

```
错误: Bind for 0.0.0.0:8501 failed: port is already allocated

解决:
1. 查看占用端口的进程
   netstat -ano | findstr :8501

2. 关闭该进程，或修改 docker-compose.yml 中的端口映射
   把 "8501:8501" 改成 "8502:8501"
   然后访问 http://localhost:8502
```

### 问题 2：Milvus 连接失败

```
错误: cannot connect to Milvus

排查:
1. 检查 Milvus 容器有没有在跑
   docker ps | grep milvus

2. 检查 Milvus 健康状态
   curl http://localhost:9091/healthz

3. 如果没跑，启动它
   docker-compose -f docker-compose-offline.yml up -d
```

### 问题 3：向量搜索没结果

```
原因: Milvus 里没有数据

解决:
1. 重新向量化文档
   cd D:\PythonProject\ragmi
   set PYTHONPATH=.
   python -m utils.txt_spliter.vector_main

2. 验证数据
   python -c "
   from pymilvus import MilvusClient
   c = MilvusClient(uri='http://127.0.0.1:19530')
   print('txt_data:', c.get_collection_stats('txt_data')['row_count'])
   "
```

## 5.3 数据备份与恢复

```bash
# ========== 备份 Milvus 数据 ==========
# 停止 Milvus
docker-compose -f docker-compose-offline.yml stop milvus

# 复制数据目录
cp -r volumes/milvus/data volumes/milvus/data-backup-$(date +%Y%m%d)

# 重启 Milvus
docker-compose -f docker-compose-offline.yml start milvus

# ========== 恢复 Milvus 数据 ==========
# 停止 Milvus
docker-compose -f docker-compose-offline.yml stop milvus

# 恢复数据
rm -rf volumes/milvus/data
cp -r volumes/milvus/data-backup-20260521 volumes/milvus/data

# 重启 Milvus
docker-compose -f docker-compose-offline.yml start milvus
```

---

# 附录

## A. 文件速查表

```
┌─────────────────────────────────────────────────────────────────┐
│                         部署相关文件                            │
├─────────────────┬───────────────────────────────────────────────┤
│  文件名          │  用途                                        │
├─────────────────┼───────────────────────────────────────────────┤
│  Dockerfile      │  定义如何构建 app 镜像                       │
│  docker-compose.yml │ 定义 app + Milvus 如何运行               │
│  docker-compose-offline.yml │ 官方推荐的 Milvus 3容器部署      │
│  docker-compose-milvus.yml │ 单 Milvus 容器（备用）            │
│  requirements.txt │ Python 依赖列表                            │
│  .env             │ 环境变量（不上传 git）                      │
└─────────────────┴───────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         文档文件                                 │
├─────────────────────────────────────────────────────────────────┤
│  docs/mettings/Docker-Deployment-Tutorial.md  │ 保姆级部署教程 │
│  docs/mettings/Docker-Milvus-Explained.md    │ Docker 概念详解 │
│  docs/mettings/Docker-Deployment-Steps.md     │ 部署步骤详解   │
│  docs/mettings/Dockerfile-vs-Compose.md      │ 文件区别解释   │
│  docs/mettings/Milvus-Deployment-Summary.md   │ 部署问题总结   │
│  docs/mettings/Milvus-Data-Storage.md         │ 数据存储说明   │
│  docs/mettings/Attu-MultiProject.md           │ Attu 可视化    │
└─────────────────────────────────────────────────────────────────┘
```

## B. 服务端口速查

```
┌─────────────────────────────────────────────────────────────────┐
│                        端口速查                                 │
├──────────┬──────────────────────────────────────────────────────┤
│  端口     │  服务                                               │
├──────────┼──────────────────────────────────────────────────────┤
│  8501    │  Streamlit 前端（浏览器访问）                        │
│  8000    │  FastAPI 后端                                        │
│  19530   │  Milvus gRPC（客户端连接）                           │
│  9091    │  Milvus 健康检查                                     │
│  9000    │  MinIO S3 协议（内部）                               │
│  9001    │  MinIO 管理界面（内部）                              │
│  2379    │  etcd（内部）                                        │
│  3000    │  Attu 管理界面（浏览器访问）                         │
└──────────┴──────────────────────────────────────────────────────┘
```

## C. 一句话总结

```
Dockerfile  = 菜谱（怎么构建）
docker-compose = 菜单（怎么运行）

部署顺序：先搞懂架构 → 再搞懂端口 → 写 Dockerfile → 写 docker-compose

Milvus 3 容器：etcd（元数据）+ minio（向量存储）+ milvus（主服务）

端口映射：宿主机 :8501 → 容器 :8501（通过 ports 配置）

Attu：一条 docker run 命令安装，浏览器 http://localhost:3000 访问
```

---

**文档版本**: v1.0
**最后更新**: 2026-05-21
**适用项目**: RAGMI
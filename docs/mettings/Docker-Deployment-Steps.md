# Docker 部署核心步骤与架构关系

## 一、Docker 部署最重要的 5 个步骤

### 第 1 步：理清服务架构（先画图，再动手）

```
部署前必须回答的问题：

1. 有哪些服务需要运行？
   - Milvus（向量数据库）
   - Redis（缓存/消息队列）
   - App（你的 Python 应用）

2. 服务之间怎么通信？
   App → Milvus（查询向量）
   App → Redis（缓存数据）

3. 哪些端口需要对外暴露？
   用户 → App:8501, App:8000
   App → Milvus:19530
   App → Redis:6379

4. 数据怎么持久化？
   Milvus 数据 → volume
   Redis 数据 → volume
   App 代码 → volume
```

### 第 2 步：编写 docker-compose.yml（定义所有服务）

```yaml
# docker-compose.yml
services:
  # 你的应用
  app:
    build: .              # 从当前目录的 Dockerfile 构建
    ports:                # 端口映射
      - "8000:8000"      # 宿主机:容器
      - "8501:8501"
    environment:          # 环境变量
      - MILVUS_HOST=milvus
      - REDIS_HOST=redis
    depends_on:           # 启动顺序（不保证服务就绪）
      - milvus
      - redis

  # Milvus 向量数据库
  milvus:
    image: milvusdb/milvus:v2.6.16
    ports:
      - "19530:19530"    # gRPC 端口
    environment:
      ETCD_USE_EMBED_STORAGE: "true"
    volumes:
      - milvus-data:/var/lib/milvus
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 30s
      timeout: 20s
      retries: 5

  # Redis 缓存
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

volumes:
  milvus-data:
  redis-data:
```

### 第 3 步：编写 Dockerfile（构建应用镜像）

```dockerfile
# Dockerfile
FROM python:3.11-slim          # 基础镜像（操作系统 + Python）

WORKDIR /app                   # 工作目录

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .        # 复制依赖文件
RUN pip install --no-cache-dir -r requirements.txt  # 安装依赖

COPY . .                       # 复制所有代码

EXPOSE 8000 8501              # 声明需要暴露的端口

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]  # 启动命令
```

### 第 4 步：配置网络互通（Docker 自动创建）

```yaml
# Docker 自动创建虚拟网络
# 容器之间通过 服务名 互相访问

# app 容器内访问 milvus：
MilvusClient(uri="http://milvus:19530")   # 用服务名，不用 IP

# app 容器内访问 redis：
Redis(host="redis", port=6379)

# 宿主机访问容器：
http://localhost:8501       # Streamlit
http://localhost:8000       # FastAPI
http://localhost:19530      # Milvus
http://localhost:6379       # Redis
```

### 第 5 步：处理数据持久化（volume）

```yaml
# 数据存储在 volume 中，删除容器不丢数据

volumes:
  milvus-data:               # 定义 volume
  redis-data:
  app-data:

services:
  milvus:
    volumes:
      - milvus-data:/var/lib/milvus   # 容器内路径:volume名
```

---

## 二、端口关系详解

### 2.1 端口映射的本质

```
宿主机（你的电脑）                容器内部

┌─────────────────────┐        ┌─────────────────────┐
│                     │        │                     │
│  8000 (对外)         │ ←───   │  8000 (服务监听)    │
│                     │  映射   │                     │
└─────────────────────┘        └─────────────────────┘

"8000:8000" = 宿主机8000 → 容器8000
```

### 2.2 RAGMI 完整端口映射

```
┌─────────────────────────────────────────────────────────────────┐
│                         宿主机（Windows）                        │
│                                                                 │
│   浏览器访问                                                      │
│       ↓                                                          │
│   http://localhost:8501  ──→  Streamlit 前端容器 :8501           │
│   http://localhost:8000  ──→  FastAPI 后端容器 :8000             │
│   http://localhost:19530 ──→  Milvus 容器 :19530（调试用）        │
│   http://localhost:9091  ──→  Milvus 健康检查 :9091              │
│   http://localhost:6379  ──→  Redis 容器 :6379（如果部署）        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Docker 内部网络（milvus-net）
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     app 容器内部                                 │
│                                                                 │
│   代码里连接:                                                     │
│   - MilvusClient("http://milvus:19530")     ← 用服务名           │
│   - Redis(host="redis", port=6379)           ← 用服务名           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 端口分类

| 类型 | 端口 | 可见性 | 用途 |
|------|------|--------|------|
| 对外暴露 | 8501, 8000 | 宿主机/浏览器 | 用户访问 |
| 内部暴露 | 19530, 6379 | 宿主机 | 调试/其他服务 |
| 内部专用 | 2379, 9000 | Docker网络 | 容器间通信 |

---

## 三、数据关系详解

### 3.1 服务间数据流向

```
┌─────────────────────────────────────────────────────────────────┐
│                         数据流向                                 │
└─────────────────────────────────────────────────────────────────┘

1. 用户上传文档时：
   浏览器 → Streamlit(:8501) → FastAPI(:8000) → Milvus(:19530)
                                           ↓
                                    txt/ 目录（volume）

2. 向量化时：
   txt/文件 → Splitter切分 → Ollama嵌入 → Milvus存储

3. 用户查询时：
   浏览器 → FastAPI → Milvus搜索 → LLM生成 → 返回浏览器

4. 使用 Redis 缓存时：
   首次查询 → Milvus查询 → Redis缓存
   再次查询 → Redis命中 → 直接返回
```

### 3.2 数据持久化关系

```
┌─────────────────────────────────────────────────────────────────┐
│                     volume 持久化机制                            │
└─────────────────────────────────────────────────────────────────┘

   删除容器             删除容器 + volume            删除 volume
   (代码在)              (数据在 volume)             (数据丢失)

   ✅ 代码在              ✅ 数据在                   ❌ 全部丢失


Milvus volume 示例：
┌──────────────────────────────────────────┐
│  /var/lib/milvus  ←── volume 挂载点       │
│                                          │
│  ├── by-db/                              │
│  │   └── milvus.db                      │
│  ├── files/                              │
│  │   └── segment data                   │
│  └── log/                                │
│                                          │
└──────────────────────────────────────────┘

删除容器：docker compose down            ✓ 数据保留
删除 volume：docker compose down -v     ❌ 数据丢失
```

### 3.3 服务间调用关系

```
                    用户请求
                        │
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                      app 容器                               │
│                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │  Streamlit  │ →  │   FastAPI   │ →  │   Agent     │      │
│  │  (前端UI)    │    │  (路由)     │    │  (业务逻辑) │      │
│  └─────────────┘    └─────────────┘    └─────────────┘      │
│                                             │                │
│                                             ↓                │
│                                    ┌─────────────────┐       │
│                                    │   RagTool       │       │
│                                    │   ChatTool      │       │
│                                    └─────────────────┘       │
└─────────────────────────────────────────────────────────────┘
                       │                    │
                       ↓                    ↓
              ┌──────────────┐     ┌──────────────┐
              │    Redis     │     │    Milvus    │
              │  (缓存/会话)  │     │  (向量检索)   │
              │  :6379       │     │  :19530       │
              └──────────────┘     └──────────────┘
```

---

## 四、已部署 Milvus，想再加 Redis 的步骤

### 4.1 修改 docker-compose.yml

```yaml
# 添加 Redis 服务
services:
  # 现有的 milvus 服务保持不动
  milvus:
    image: milvusdb/milvus:v2.6.16
    ports:
      - "19530:19530"
    volumes:
      - milvus-data:/var/lib/milvus

  # 新增 Redis
  redis:
    image: redis:7-alpine          # 官方镜像，轻量
    container_name: docker-redis   # 容器名称
    ports:
      - "6379:6379"                # 暴露到宿主机
    volumes:
      - redis-data:/data           # 持久化
    command: redis-server --appendonly yes  # 开启 AOF 持久化

volumes:
  milvus-data:                     # 已有
  redis-data:                       # 新增
```

### 4.2 在代码中使用 Redis

```python
# 安装 redis 包
# pip install redis

import redis

# 连接 Redis（容器间用服务名）
client = redis.Redis(
    host='redis',           # docker-compose 服务名
    port=6379,
    decode_responses=True
)

# 使用示例：缓存会话
def get_cached_session(session_id):
    data = client.get(f"session:{session_id}")
    return json.loads(data) if data else None

def cache_session(session_id, data):
    client.setex(f"session:{session_id}", 3600, json.dumps(data))
```

### 4.3 一键启动/停止

```bash
# 启动所有服务
docker-compose up -d

# 查看运行状态
docker ps

# 查看日志
docker logs -f docker-redis

# 停止所有服务（数据保留）
docker-compose down

# 停止并删除数据卷（清空数据）
docker-compose down -v
```

---

## 五、部署 Checklist（每次部署前检查）

```
□ 1. 服务有哪些？
□ 2. 服务之间怎么通信？（用服务名，不用 IP）
□ 3. 哪些端口对外暴露？
□ 4. 数据是否需要持久化？（用 volume）
□ 5. 环境变量是否正确传递？
□ 6. healthcheck 是否配置？
□ 7. depends_on 启动顺序是否正确？（但不保证服务就绪）
□ 8. 代码中连接地址是否用服务名？
```

---

## 六、常见错误

### 错误 1：用 localhost 而不是服务名

```python
# 错误（容器内无法访问宿主机 localhost）
client = MilvusClient(uri="http://localhost:19530")

# 正确（用 docker-compose 服务名）
client = MilvusClient(uri="http://milvus:19530")

# 正确（从容器访问宿主机，用 host.docker.internal）
client = MilvusClient(uri="http://host.docker.internal:19530")
```

### 错误 2：容器间网络不通

```yaml
# 检查是否在同一网络
services:
  app:
    networks:
      - milvus-net    # 确保在同一个网络
  milvus:
    networks:
      - milvus-net
```

### 错误 3：volume 挂载路径错误

```yaml
# 正确
volumes:
  - milvus-data:/var/lib/milvus

# 错误（路径写错）
volumes:
  - milvus-data:/opt/data  # 应该是 /var/lib/milvus
```

---

## 七、快速参考

| 操作 | 命令 |
|------|------|
| 启动所有服务 | `docker-compose up -d` |
| 查看运行状态 | `docker ps` |
| 查看服务日志 | `docker logs -f <容器名>` |
| 进入容器 | `docker exec -it <容器名> bash` |
| 停止所有服务 | `docker-compose down` |
| 删除并清空数据 | `docker-compose down -v` |
| 重启某个服务 | `docker-compose restart <服务名>` |
| 查看网络 | `docker network ls` |
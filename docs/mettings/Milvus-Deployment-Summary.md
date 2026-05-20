# Milvus 部署问题总结与解决方案

## 一、初始部署失败的原因

### 1.1 错误现象

使用 `docker-compose-milvus.yml`（基于 `milvusdb/milvus:v2.3.14` 独立容器）部署时：

```
# 启动命令
docker-compose -f docker-compose-milvus.yml up -d

# 查看状态：容器退出
docker ps -a  # 显示 milvus-standalone 已退出

# 日志错误
curl http://localhost:9091/healthz  # 无响应
```

### 1.2 根本原因：嵌入式 etcd 的 IPv6 监听问题

**Milvus standalone 模式使用嵌入式 etcd**，而这个 etcd 在 Docker 容器中绑定到了 `localhost:2379`。

**问题链路：**
```
1. Milvus 启动时，嵌入式 etcd 监听 [::]:2379（IPv6 全端口）
2. 但 etcd 进程内部实际只支持 IPv4
3. Windows Docker Desktop + WSL2 环境中，localhost 解析为 [::1] (IPv6)
4. 当 Milvus 尝试连接 etcd 时：[::1]:2379 被拒绝
5. 容器随即退出
```

**为什么在 Linux 服务器上没问题：**
- Linux 的 Docker 默认使用 bridge 网络模式
- localhost 解析为 127.0.0.1 (IPv4)
- etcd 能正常响应

**为什么在 Windows Docker Desktop 上有问题：**
- WSL2 后端：Docker 运行在 WSL2 虚拟机内
- 网络地址转换复杂，IPv6 环回地址处理不一致
- 嵌入式 etcd 无法正常工作

### 1.3 不是 Milvus 本身的问题

Milvus 官方本身就**不推荐**在生产环境使用 standalone 模式。官方文档明确说明：

> For production deployment, use the docker-compose setup with separate etcd and minio containers.

独立容器只是用于开发/测试目的，而开发测试也建议使用官方 docker-compose 配置。

---

## 二、正确部署 Milvus 的方法

### 2.1 官方推荐的架构（3 容器）

```yaml
# docker-compose-offline.yml（从 GitHub releases 下载的标准配置）
services:
  etcd:         # 元数据存储（etcd）
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.25
    ...

  minio:        # 对象存储（MinIO）
    container_name: milvus-minio
    image: minio/minio:latest
    ...

  milvus:       # 主服务
    container_name: milvus-standalone
    image: milvusdb/milvus:v2.6.16
    depends_on:
      - etcd
      - minio
    ...
```

**三个容器的作用：**

| 容器 | 作用 | 端口 |
|------|------|------|
| etcd | 存储 Milvus 元数据（collection 名称、schema 等） | 2379 |
| minio | 存储向量数据本身（S3 兼容对象存储） | 9000, 9001 |
| milvus | 主服务，处理 gRPC 请求 | 19530, 9091 |

### 2.2 部署步骤

```bash
# 1. 使用官方配置文件（非独立容器）
wget https://github.com/milvus-io/milvus/releases/download/v2.6.16/milvus-standalone-docker-compose.yml
mv milvus-standalone-docker-compose.yml docker-compose-offline.yml

# 2. 启动
docker-compose -f docker-compose-offline.yml up -d

# 3. 等待约 90 秒后验证
curl http://localhost:9091/healthz
# 返回: {"status":"OK"}

# 4. 查看容器状态
docker ps
# 显示 3 个容器运行中：milvus-etcd, milvus-minio, milvus-standalone
```

---

## 三、核心 Docker 概念

### 3.1 Container Network（容器网络）

```
宿主机 (Windows) ──────────────────────────────────────

  Docker Desktop (WSL2) ─────────────────────────────
       │
       ├── milvus-standalone:19530  → 暴露给宿主机
       ├── milvus-standalone:9091   → 暴露给宿主机 (健康检查)
       │
       └── 内部网络 (milvus-net)
            ├── milvus-standalone (内部 IP: 172.x.x.x)
            ├── etcd (内部 IP: 172.x.x.x:2379)        ← 不暴露
            └── minio (内部 IP: 172.x.x.x:9000)        ← 不暴露
```

**关键概念：**
- **Port Mapping** (`ports: "19530:19530"`): 将容器内部端口映射到宿主机
- **Internal Network**: 容器间通信的网络，外部无法直接访问
- **host.docker.internal**: 从容器内部访问宿主机的方式

### 3.2 Volume（数据卷）

```yaml
volumes:
  milvus-data:
    driver: local
```

- 容器删除后数据不会丢失
- 数据持久化存储在宿主机

### 3.3 Health Check（健康检查）

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
  interval: 30s
  timeout: 20s
  retries: 5
  start_period: 120s
```

- Docker 定期检查容器健康状态
- `start_period: 120s`: 允许容器 120 秒内启动（Milvus 需要时间初始化）

### 3.4 Dependency（依赖关系）

```yaml
depends_on:
  - etcd
  - minio
```

- Milvus 启动前等待 etcd 和 minio 就绪
- 但 `depends_on` 只保证启动顺序，不保证服务就绪

---

## 四、代码修改详情

### 4.1 `utils/txt_spliter/vector_main.py`

**修改前（使用 langchain_milvus）：**
```python
from langchain_milvus import Milvus

vector_store = Milvus.from_documents(
    documents=documents,
    embedding=embed_model.embedding,  # 问题：langchain_milvus 使用旧的 ORM API
    collection_name=milvus_config.get("collection_name", "txt_data"),
    connection_args={"host": ..., "port": ...},
    drop_old=False,
)
```

**错误原因：**
`langchain_milvus` 0.3.x 内部使用 `pymilvus.orm.Collection`（ORM 风格，即将废弃），需要先 `connections.connect()` 建立连接，但新的 `MilvusClient` 不走这套 API，导致 "should create connection first" 错误。

**修改后（使用 raw pymilvus）：**
```python
from pymilvus import MilvusClient, DataType
from langchain_ollama import OllamaEmbeddings

# 1. 连接 Milvus
client = MilvusClient(uri=f"http://{host}:{port}")

# 2. 创建 Schema
schema = client.create_schema(enable_dynamic_field=True)
schema.add_field(field_name='id', datatype=DataType.INT64, is_primary=True, auto_id=True)
schema.add_field(field_name='vector', datatype=DataType.FLOAT_VECTOR, dim=dim)
schema.add_field(field_name='text', datatype=DataType.VARCHAR, max_length=65535)

# 3. 创建 Collection
client.create_collection(collection_name=coll_name, schema=schema)

# 4. 插入数据（使用 dict list 格式）
entities = [{'vector': vectors[i], 'text': texts[i]} for i in range(len(texts))]
result = client.insert(collection_name=coll_name, data=entities)

# 5. 创建索引（必须先创建索引才能加载）
index_params = client.prepare_index_params(field_name='vector', index_type='AUTOINDEX', metric_type='COSINE')
client.create_index(collection_name=coll_name, index_params=index_params)

# 6. 加载 Collection
client.load_collection(collection_name=coll_name)
```

**关键 API 说明：**

| 操作 | API | 说明 |
|------|-----|------|
| 连接 | `MilvusClient(uri='http://host:port')` | 使用 MilvusClient（v2.6+ 推荐） |
| Schema | `client.create_schema()` + `schema.add_field()` | 定义集合结构 |
| 插入 | `client.insert(collection_name=..., data=[{...}])` | 批量插入，data 是 dict list |
| 索引 | `client.prepare_index_params()` + `create_index()` | 必须先创建索引才能加载 |
| 加载 | `client.load_collection()` | 加载后才能搜索 |
| 搜索 | `client.search(collection_name=..., data=[vec], limit=..., output_fields=[...])` | 返回 Hit 对象列表 |

### 4.2 `core/rags/rags.py`

**修改前：**
```python
from langchain_milvus import Milvus

vector_store = Milvus(
    embedding_function=embed_model.embedding,
    collection_name=...,
    connection_args={"host": ..., "port": ...},
)
docs = vector_store.similarity_search(query, k=top_k)
chunks = [doc.page_content for doc in docs]
```

**修改后：**
```python
from pymilvus import MilvusClient
from langchain_ollama import OllamaEmbeddings

self._embed = OllamaEmbeddings(model='bge-large', base_url='http://localhost:11434')
self._client = MilvusClient(uri=f"http://{host}:{port}")

# 搜索时手动做 embedding
query_vector = self._embed.embed_query(query)
results = self._client.search(
    collection_name=self._collection_name,
    data=[query_vector],
    limit=top_k,
    output_fields=['text']
)
chunks = [hit.entity.get('text', '') for hit in results[0]]
```

**改动原因：**
langchain_milvus 的 `similarity_search` 内部调用了有问题的 ORM API，直接使用 `MilvusClient` 可以完全控制，避免版本兼容问题。

### 4.3 新增文件

| 文件 | 作用 |
|------|------|
| `docker-compose-offline.yml` | 官方推荐的 3 容器部署配置 |
| `docker-compose-milvus.yml` | 单 Milvus 容器配置（备用） |
| `docker-compose.yml` | App + Milvus 一体化部署 |
| `Dockerfile` | App 容器化 |
| `.env.example` | 环境变量模板 |

---

## 五、Milvus 部署核心要点（速查）

### 5.1 为什么不能用独立容器？

嵌入式 etcd 在 Windows Docker Desktop（WSL2）上有 IPv6 连接问题。

### 5.2 正确部署命令

```bash
# 方式一：官方配置（推荐）
docker-compose -f docker-compose-offline.yml up -d
curl http://localhost:9091/healthz  # 等待返回 {"status":"OK"}

# 方式二：一体化部署（App + Milvus）
docker-compose up -d
```

### 5.3 代码层面注意

- 使用 `pymilvus.MilvusClient`（新 API），不用 `pymilvus.orm.Collection`（旧 ORM API）
- 搜索前必须：`create_index()` → `load_collection()`
- 插入数据格式：`data=[{'vector': [...], 'text': '...'}]`（dict list，不是 dict of lists）

### 5.4 验证部署成功

```python
from pymilvus import MilvusClient

client = MilvusClient(uri='http://127.0.0.1:19530')
print(client.list_collections())  # 应显示 ['txt_data']
print(client.get_collection_stats('txt_data'))  # 应显示片段数量
```

---

## 六、相关技术文档

- [Milvus 官方安装文档](https://milvus.io/docs/install_standalone-docker-compose.md)
- [Milvus Client Python SDK](https://milvus.io/docs/sdk-python-install.md)
- [Docker Compose 文档](https://docs.docker.com/compose/)
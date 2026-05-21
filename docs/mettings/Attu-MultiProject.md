# Attu 可视化工具 + 多项目 Milvus 共用方案

## 一、Attu 是什么？怎么安装？

### 1.1 Attu 是独立的应用，不是 Milvus 的一部分

```
Attu ≈ Milvus 的图形化管理界面（像 Navicat）

不是 Milvus 自带的，需要单独部署
但它是轻量级的，一个命令就能启动
```

### 1.2 Attu 安装（一条命令）

```bash
docker run -d \
  --name attu \
  -p 8000:8000 \
  -e MILVUS_HOST=host.docker.internal \
  -e MILVUS_PORT=19530 \
  zilliz/attu:latest
```

```
解释：
--name attu              ← 给容器起个名字叫 attu
-p 8000:8000             ← 端口映射（宿主机:容器）
-e MILVUS_HOST=...        ← 告诉 Attu 你的 Milvus 在哪
```

启动后访问：`http://localhost:8000`

### 1.3 Attu 可以管理多个 Milvus

```
Attu 只是一个"客户端"，它连接到你指定的 Milvus

┌─────────────────────────────────────────────────────────────┐
│                                                              │
│   Attu (浏览器 http://localhost:8000)                        │
│         ↓                                                    │
│    连接 Milvus-A（项目1）     → 查看/管理                     │
│    连接 Milvus-B（项目2）     → 切换连接地址                  │
│    连接 Milvus-C（项目3）     → 想连哪个连哪个                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘

一个 Attu 可以管理所有 Milvus 实例！
不需要每个项目装一个 Attu
```

---

## 二、多项目 Milvus 共用方案

### 2.1 核心问题：需要多少个 Milvus？

```
你的担心：
每个项目都部署 Milvus → 会有很多个 Milvus 容器 → 占用资源

实际情况：
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  方案 A：每个项目独立 Milvus（推荐用于开发）                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │ 项目 A   │  │ 项目 B   │  │ 项目 C   │                   │
│  │ Milvus-A │  │ Milvus-B │  │ Milvus-C │                   │
│  └──────────┘  └──────────┘  └──────────┘                   │
│  优点：隔离，互不影响                                        │
│  缺点：资源占用多                                           │
│                                                              │
│  方案 B：所有项目共用一个 Milvus（推荐用于生产）              │
│  ┌──────────────────────────────────────┐                   │
│  │            一个 Milvus                │                   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐   │                   │
│  │  │项目A集合│ │项目B集合│ │项目C集合│   │                   │
│  │  └────────┘ └────────┘ └────────┘   │                   │
│  └──────────────────────────────────────┘                   │
│  优点：资源占用少                                            │
│  缺点：需要区分集合名称（项目A_collection）                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 开发环境（你的情况）：方案 A

```
你是个人开发环境，项目不多，每个项目独立 Milvus 完全可以

Milvus 很轻量（几百 MB 内存），几个同时跑也没问题
```

### 2.3 生产环境：方案 B

```
多个项目共用一个 Milvus，用不同的集合名区分

例如：
- 项目 A 的数据 → collection_name = "project_a_docs"
- 项目 B 的数据 → collection_name = "project_b_docs"

在 docker-compose.yml 里：
  environment:
    - MILVUS_COLLECTION=project_a_docs   # 每个项目配置不同的集合名
```

---

## 三、查看容器内部（映射关系）

### 3.1 你的问题：为什么看不到容器里的 /var/lib/milvus

```
你看到的目录结构：
D:\PythonProject\ragmi\
└── volumes/
    └── milvus/
        └── data/
            └── cache/     ← 这里看起来是空的！

但实际 Milvus 数据在：
容器内 /var/lib/milvus

映射关系：
宿主机 D:\PythonProject\ragmi\volumes\milvus\data
     ↓
容器内 /var/lib/milvus
```

### 3.2 为什么 volumes/milvus/data 里看起来是空的？

```
可能原因：
1. Milvus 刚启动，数据还没完全写入
2. 数据存在容器内的 tmpfs（内存）里
3. 你用 docker-compose-offline.yml 启动的是旧容器

检查方法：
docker exec milvus-standalone ls -la /var/lib/milvus
```

### 3.3 正确查看数据的方法

```bash
# 方法 1：进入容器查看
docker exec -it milvus-standalone bash
ls -la /var/lib/milvus

# 方法 2：用 du 查看大小
docker exec milvus-standalone du -sh /var/lib/milvus

# 方法 3：用 Python API 查看
python -c "
from pymilvus import MilvusClient
client = MilvusClient(uri='http://127.0.0.1:19530')
print('数据条数:', client.get_collection_stats('txt_data')['row_count'])
"
```

### 3.4 端口映射的原理（类比）

```
真实场景（医院）：

你（在医院外部）
  ↓ 访问
挂号窗口 :8000  ← 暴露给外部的端口
  ↓ 内部传递
诊室 :8080      ← 内部端口，外部看不到

Docker 容器：

宿主机（你的电脑）
  ↓ 访问
8501  ← 暴露给外部的端口（ports: "8501:8501"）
  ↓ 映射到
8501  ← 容器内部端口

类似：
宿主机端口 :8501 → 映射到 → 容器内端口 :8501
```

### 3.5 查看容器端口映射

```bash
# 查看所有容器及其端口映射
docker ps

# 输出示例：
# CONTAINER ID   IMAGE                PORTS
# a1b2c3d4e5f6   milvusdb/milvus     0.0.0.0:19530->19530/tcp, 0.0.0.0:9091->9091/tcp

# 解释：
# 0.0.0.0:19530->19530/tcp
#   宿主机19530 → 容器19530 (TCP协议)

# 查看某个容器的详细信息
docker port milvus-standalone

# 查看容器 IP（容器间通信用）
docker inspect milvus-standalone --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
```

---

## 四、实际命令操作

### 4.1 安装 Attu（一步到位）

```bash
# 启动 Attu
docker run -d \
  --name attu \
  -p 8000:8000 \
  -e MILVUS_HOST=host.docker.internal \
  -e MILVUS_PORT=19530 \
  zilliz/attu:latest

# 等待 30 秒后访问
# 浏览器打开 http://localhost:8000
```

**注意**：如果 8000 端口被占用（你已经有 FastAPI 在 8000），换一个端口：

```bash
docker run -d \
  --name attu \
  -p 3000:3000 \
  -e MILVUS_HOST=host.docker.internal \
  -e MILVUS_PORT=19530 \
  -e PORT=3000 \
  zilliz/attu:latest

# 访问 http://localhost:3000
```

### 4.2 查看 Milvus 数据（不用 Attu）

```python
# 保存这个脚本为 check_milvus.py
from pymilvus import MilvusClient

client = MilvusClient(uri='http://127.0.0.1:19530')

print("=" * 50)
print("Milvus 数据概览")
print("=" * 50)

# 所有集合
collections = client.list_collections()
print(f"\n集合数量: {len(collections)}")
print(f"集合列表: {collections}")

# 每个集合的统计
print("\n详细统计:")
for coll in collections:
    stats = client.get_collection_stats(coll)
    print(f"  - {coll}: {stats['row_count']} 条")

# 测试搜索 txt_data
print("\n测试搜索 txt_data:")
results = client.search(
    collection_name='txt_data',
    data=[[0.05] * 1024],  # 随便一个查询向量
    limit=2,
    output_fields=['text']
)
for r in results[0]:
    text = r.entity.get('text', '')[:80]
    print(f"  距离: {r.distance:.4f}, 文本: {text}...")

print("\n完成！")
```

运行：

```bash
python check_milvus.py
```

---

## 五、多项目 Milvus 共用策略（总结）

### 5.1 开发环境（项目少）

```
每个项目独立的 Milvus，干净隔离

项目 A → Milvus-A (端口 19530)
项目 B → Milvus-B (端口 19531)
项目 C → Milvus-C (端口 19532)

Attu：装一个就够了，想看哪个就连哪个
```

### 5.2 生产环境（多项目）

```
所有项目共用一个 Milvus，用集合名隔离

Milvus (端口 19530)
  ├── project_a_txt_data
  ├── project_b_documents
  └── project_c_knowledge

Attu：装一个，切换集合查看
```

### 5.3 命令速查

```bash
# 查看所有 Milvus 相关容器
docker ps | grep milvus

# 查看某个 Milvus 的数据量
docker exec milvus-standalone du -sh /var/lib/milvus

# 重启 Milvus
docker-compose -f docker-compose-offline.yml restart milvus

# 停止 Milvus
docker-compose -f docker-compose-offline.yml down

# 启动 Attu
docker start attu

# 停止 Attu
docker stop attu
```

---

## 六、一句话总结

```
Attu 安装：一条 docker run 命令，就能管理所有 Milvus

多项目 Milvus：
- 开发环境 → 每个项目独立 Milvus（不麻烦，资源占用小）
- 生产环境 → 所有项目共用一个（用集合名区分）

端口映射：
- 宿主机 :8501 → 容器内 :8501（通过 ports 配置）
- 容器内 /var/lib/milvus → 宿主机 volumes/milvus/data

查看容器内数据：
docker exec -it 容器名 bash   ← 进入容器
ls -la /var/lib/milvus       ← 查看数据目录
```
# Milvus 数据存储与可视化

## 一、向量化后的数据存在哪里？

### 1.1 你的数据不在 `data/` 文件夹

```
D:\PythonProject\ragmi\
├── data/
│   ├── chroma.sqlite3     ← 这是旧的 ChromaDB 数据（不再使用）
│   └── bbf6c685.../        ← 其他文件夹
│
├── volumes/               ← Milvus 的数据在这里！
│   └── milvus/
│       └── data/          ← Milvus 容器内的数据映射到本地
│
└── txt/                   ← 原始文档（源文件）
```

### 1.2 Milvus 数据实际存储位置

```
Milvus 数据路径：容器内 /var/lib/milvus
               ↓
映射到本地：D:\PythonProject\ragmi\volumes\milvus\data
```

```bash
# 查看 Milvus 容器内有多少数据
docker exec milvus-standalone du -sh /var/lib/milvus
```

### 1.3 为什么看不到具体内容？

```
原始文本 (.txt)          1024维向量                      二进制文件
┌──────────────┐        ┌──────────────┐        ┌──────────────┐
│ "人工智能..." │ --→   │ [0.034, ...] │ --→   │ milvus 内部  │
└──────────────┘ embed  └──────────────┘ store  │   存储格式    │
                             ↓                     │  (二进制)     │
                        Milvus 容器内存              └──────────────┘

你无法直接"打开" milvus 文件看到内容，就像无法直接打开 MySQL 的 .frm 文件一样
```

---

## 二、你的数据状态

### 2.1 向量化情况

```
✓ 已完成向量化

txt/ 文件夹中的文档：
- 01_RAG_intro_md.txt
- 02_preparation_md.txt
- 03_get_start_rag_md.txt
- CNKI-20251201184820820.txt
- note_md.txt
- ... 共 13 个文件

切分并存储到 Milvus：
- 共 1429 个文本片段 (chunks)
- 每个片段约 300 字符
- 向量维度：1024
- 存储位置：Milvus txt_data 集合
```

### 2.2 验证数据存在

```python
# 用 Python 可以查询 Milvus 里有多少数据
from pymilvus import MilvusClient

client = MilvusClient(uri='http://127.0.0.1:19530')
print('集合列表:', client.list_collections())
print('txt_data 行数:', client.get_collection_stats('txt_data')['row_count'])
```

输出：
```
集合列表: ['txt_data', 'test_small', 'test_new', ...]
txt_data 行数: 1429
```

---

## 三、有没有像 Navicat 一样的可视化工具？

### 3.1 有！Milvus 官方提供 Attu

```
Navicat（MySQL可视化）= Attu（Milvus可视化）

Attu 是 Milvus 官方出品的可视化管理系统
可以：
- 查看所有集合 (collections)
- 查看数据条数
- 执行搜索测试
- 管理集合（创建/删除）
- 查看索引状态
```

### 3.2 Attu 部署方式

**方式一：用 Docker 快速启动 Attu**

```bash
docker run -d \
  --name attu \
  -p 8000:8000 \
  -e MILVUS_HOST=host.docker.internal \
  -e MILVUS_PORT=19530 \
  -e METADATA_HOST=host.docker.internal \
  -e METADATA_PORT=3305 \
  zilliz/attu:latest
```

然后打开浏览器访问：`http://localhost:8000`

**方式二：使用 Milvus Manager（另一个选择）**

```bash
docker run -d \
  --name milvus-manager \
  -p 9090:9090 \
  milvusdb/milvus-manager:latest
```

访问：`http://localhost:9090`

### 3.3 Attu 界面能做什么？

```
┌─────────────────────────────────────────────────────────────┐
│                        Attu 界面                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Collections（集合）                                         │
│  ├── txt_data          ← 你的向量数据                        │
│  │   ├── Row count: 1429                                    │
│  │   ├── Dimension: 1024                                    │
│  │   └── Index: AUTOINDEX (COSINE)                          │
│  │                                                             │
│  ├── test_small        ← 测试数据（可删除）                  │
│  └── ...                                                      │
│                                                              │
│  操作：                                                       │
│  - 点击集合查看详情                                           │
│  - 搜索测试（输入文本看返回结果）                             │
│  - 删除集合                                                   │
│  - 查看性能指标                                               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 最简单的方式：用代码查看

如果你不想装额外的可视化工具，可以用 Python 直接查看：

```python
from pymilvus import MilvusClient

client = MilvusClient(uri='http://127.0.0.1:19530')

# 1. 查看所有集合
print("所有集合:", client.list_collections())

# 2. 查看集合统计
for coll in client.list_collections():
    stats = client.get_collection_stats(coll)
    print(f"{coll}: {stats['row_count']} 条数据")

# 3. 查看 txt_data 里前3条数据
results = client.query(
    collection_name='txt_data',
    filter='',
    output_fields=['text'],
    limit=3
)
for r in results:
    print(f"ID: {r['id']}, Text: {r['text'][:100]}...")

# 4. 测试搜索
query_vec = [[0.1] * 1024]  # 需要真实的 query 向量
results = client.search(
    collection_name='txt_data',
    data=query_vec,
    limit=3,
    output_fields=['text']
)
```

---

## 四、清理测试数据（可选）

如果你的 Milvus 里有很多测试集合，可以删除它们：

```python
from pymilvus import MilvusClient

client = MilvusClient(uri='http://127.0.0.1:19530')

# 删除不需要的测试集合
test_collections = ['test_small', 'test_new', 'test_schema', 'test_insert']

for coll in test_collections:
    if client.has_collection(coll):
        client.drop_collection(coll)
        print(f"已删除: {coll}")

print("保留的集合:", client.list_collections())
```

---

## 五、常用命令总结

```bash
# 查看 Milvus 容器内的数据大小
docker exec milvus-standalone du -sh /var/lib/milvus

# 查看集合列表（用 Python）
docker exec -it milvus-standalone milvus-cli show collections

# 重启 Milvus
docker-compose -f docker-compose-offline.yml restart milvus

# 备份数据（复制 volume）
cp -r volumes/milvus/data volumes/milvus/data-backup
```

---

## 一句话总结

```
你的向量数据：
- 存在 Milvus 容器内（/var/lib/milvus）
- 映射到本地（volumes/milvus/data）
- 你无法直接"看到"内容（二进制格式）
- 但可以用 Attu 可视化工具管理
- 或者用 Python 代码查询

建议：安装 Attu（docker 一条命令），浏览器打开 http://localhost:8000
```
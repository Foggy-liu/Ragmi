# Docker 部署执行手册（Step by Step）

## 目标读者

本手册面向需要快速部署 RAGMI 项目的开发者，提供清晰的执行步骤。

## 前置条件

```
✓ Docker Desktop 已安装并运行
✓ 已克隆 RAGMI 项目到本地
✓ 网络正常（能访问 Docker Hub）
```

---

## Step 0：检查环境

```bash
# 检查 Docker 是否安装
docker --version
# 预期输出: Docker version 20.10.x 或更高

# 检查 Docker 是否运行
docker ps
# 预期输出: CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS
#          （有内容或空都行，只要不报错）
```

**如果报错 "docker 不是内部或外部命令"**：
- 去 https://www.docker.com/products/docker-desktop/ 下载安装
- 重启电脑
- 重新执行上述检查

---

## Step 1：启动 Milvus（向量数据库）

### 1.1 选择部署方式

```
方式 A：使用官方 3 容器部署（推荐）
→ docker-compose-offline.yml

方式 B：使用单容器部署（备用，可能有问题）
→ docker-compose-milvus.yml
```

### 1.2 启动 Milvus

```bash
# 进入项目目录
cd D:\PythonProject\ragmi

# 启动 Milvus（官方 3 容器模式）
docker-compose -f docker-compose-offline.yml up -d
```

### 1.3 等待 Milvus 启动（约 90 秒）

```bash
# 检查容器状态
docker ps
# 预期：看到 milvus-etcd, milvus-minio, milvus-standalone 三个容器

# 检查 Milvus 健康状态
curl http://localhost:9091/healthz
# 预期：{"status":"OK"}
```

**如果返回的不是 OK**：等待 30 秒后再试，Milvus 启动需要时间。

---

## Step 2：向量化文档（只需要做一次）

### 2.1 为什么要这一步？

```
用户提问 → 系统搜索相关文档 → 需要先有向量数据
Milvus 存的是向量，不是原始文本
所以要先"向量化"文档，存进去
```

### 2.2 执行向量化

```bash
# 进入项目目录
cd D:\PythonProject\ragmi

# 设置 Python 路径并运行向量化脚本
# Windows:
set PYTHONPATH=.
python -m utils.txt_spliter.vector_main

# Mac/Linux:
# export PYTHONPATH=.
# python -m utils.txt_spliter.vector_main
```

### 2.3 预期输出

```
找到 13 个txt文件
正在处理文件: 01_RAG_intro_md.txt
...
Embedding 维度: 1024
创建集合: txt_data
正在为 1429 个文档片段生成 embedding...
已插入 100/1429 个片段
...
已插入 1429 个片段
正在创建索引...
正在加载集合...
Milvus 向量库创建成功！
文档片段数: 1429
```

### 2.4 验证数据

```bash
python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://127.0.0.1:19530')
print('集合列表:', c.list_collections())
print('txt_data 条数:', c.get_collection_stats('txt_data')['row_count'])
"
# 预期输出:
# 集合列表: ['txt_data']
# txt_data 条数: 1429
```

---

## Step 3：启动应用（FastAPI + Streamlit）

### 3.1 方式一：Docker 部署（一键启动）

```bash
# 构建并启动所有服务
docker-compose up -d --build

# 查看状态
docker ps
# 预期：看到 docker-ragmi-app 容器
```

### 3.2 方式二：手动启动（开发调试用）

```bash
# 终端 1：启动 FastAPI
cd D:\PythonProject\ragmi
python main.py

# 终端 2：启动 Streamlit
cd D:\PythonProject\ragmi
streamlit run main_web.py
```

### 3.3 选择建议

```
Docker 部署：适合正式环境，一键启动/停止
手动启动：适合开发调试，修改代码后立即生效
```

---

## Step 4：验证部署成功

### 4.1 检查容器状态

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

**预期输出：**
```
NAMES                 STATUS         PORTS
milvus-standalone     Up 2 hours     0.0.0.0:19530->19530/tcp, 0.0.0.0:9091->9091/tcp
docker-ragmi-app     Up 10 minutes  0.0.0.0:8000->8000/tcp, 0.0.0.0:8501->8501/tcp
milvus-minio         Up 2 hours     0.0.0.0:9000->9000/tcp, 0.0.0.0:9001->9001/tcp
milvus-etcd          Up 2 hours
```

### 4.2 测试访问

打开浏览器，依次访问：

```
1. Streamlit 前端（你看到的网页界面）
   http://localhost:8501

2. FastAPI 文档（API 测试界面）
   http://localhost:8000/docs

3. Milvus 健康检查
   http://localhost:9091/healthz
   预期返回：{"status":"OK"}

4. Attu 可视化管理（如果已安装）
   http://localhost:3000
```

---

## Step 5：停止服务

```bash
# 停止所有服务（数据保留）
docker-compose down

# 停止 Milvus（如果不需要向量数据库）
docker-compose -f docker-compose-offline.yml down

# 停止所有容器
docker-compose down -v
# -v 参数会删除数据卷（清空数据）
```

---

## 常见操作清单

### 日常启动（每次开机）

```bash
# 1. 启动 Milvus
docker-compose -f docker-compose-offline.yml up -d

# 2. 等待 90 秒后启动应用
docker-compose up -d

# 3. 打开浏览器访问
#    http://localhost:8501
```

### 每次修改代码后

```bash
# 重新构建并启动
docker-compose up -d --build

# 或只重启 app 容器
docker-compose restart app
```

### 查看日志

```bash
# 查看 app 日志（实时）
docker logs -f docker-ragmi-app

# 查看 Milvus 日志
docker logs -f milvus-standalone

# 查看最近 100 行
docker logs --tail 100 docker-ragmi-app
```

### 进入容器

```bash
# 进入 app 容器
docker exec -it docker-ragmi-app bash

# 进入 Milvus 容器
docker exec -it milvus-standalone bash

# 进入后查看数据
ls -la /var/lib/milvus
```

---

## 快速命令速查表

```
┌────────────────────────────────────────────────────────────────┐
│                        命令速查                                │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  启动 Milvus          │ docker-compose -f docker-compose-offline.yml up -d  │
│  启动所有服务          │ docker-compose up -d                              │
│  停止所有服务          │ docker-compose down                              │
│  查看运行状态          │ docker ps                                        │
│  查看日志              │ docker logs -f <容器名>                         │
│  重启服务              │ docker-compose restart <服务名>                 │
│  进入容器              │ docker exec -it <容器名> bash                   │
│  向量化文档            │ set PYTHONPATH=. && python -m utils.txt_spliter.vector_main │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                        访问地址                                │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  Streamlit 前端    │ http://localhost:8501                     │
│  FastAPI 文档     │ http://localhost:8000/docs                 │
│  Milvus 健康检查  │ http://localhost:9091/healthz              │
│  Attu 可视化      │ http://localhost:3000                      │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 故障排查

### 端口被占用

```bash
# 查看端口占用
netstat -ano | findstr :8501

# 关闭占用程序，或修改 docker-compose.yml 中的端口
```

### Milvus 连接失败

```bash
# 检查容器是否在跑
docker ps | grep milvus

# 重启 Milvus
docker-compose -f docker-compose-offline.yml restart
```

### 向量化失败

```bash
# 检查 Ollama 是否在运行
curl http://localhost:11434/api/tags

# 如果没运行，启动 Ollama
ollama serve
```

---

**文档版本**: v1.0
**最后更新**: 2026-05-21
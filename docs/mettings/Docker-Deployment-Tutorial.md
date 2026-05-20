# RAGMI 项目 Docker 部署保姆级教程

## 目标

本教程结束时，你将能够：
```
□ 用一条命令启动完整的 RAGMI 系统（FastAPI + Streamlit + Milvus）
□ 知道每个服务跑在哪个端口
□ 能访问前端页面并测试聊天功能
□ 知道怎么停止和重启服务
```

---

## 第零章：先回答几个问题（判断你的环境）

### 0.1 你电脑上有没有 Docker？

打开**命令提示符**（Windows 按 Win+R，输入 `cmd`，回车），输入：

```
docker --version
```

**如果显示版本号**（如 Docker version 20.10.x），说明已安装 → 跳到 0.2

**如果显示"'docker' 不是内部或外部命令"**，说明没装 Docker → 看 0.1.1

#### 0.1.1 如果没有 Docker（Windows）

```
步骤：
1. 去 https://www.docker.com/products/docker-desktop/ 下载安装包
2. 双击安装（需要管理员权限）
3. 重启电脑
4. 打开 Docker Desktop，等待看到小鲸鱼图标（可能需要几分钟）
5. 验证：打开命令提示符，输入 docker --version
```

**注意**：Docker Desktop 需要 WSL2 后端（Windows 10/11 自带），如果提示安装 WSL2，按提示操作后重启。

### 0.2 Docker 有没有在运行？

打开命令提示符，输入：

```
docker ps
```

**如果显示类似这样**（Headers + 空或几行内容）：
```
CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS
```
说明 Docker 正在运行 → 跳到第一章

**如果显示 "error during connect"**：
```
打开 Docker Desktop，等待小鲸鱼图标变绿（不闪烁）后再试
```

---

## 第一章：理解你要部署什么

### 1.1 先不要急着敲命令，我们先"看懂"这个项目

打开项目文件夹（`D:\PythonProject\ragmi`），你会看到这些文件：

```
D:\PythonProject\ragmi\
├── main.py              ← FastAPI 后端（处理用户请求）
├── main_web.py          ← Streamlit 前端（网页界面）
├── requirements.txt     ← Python 依赖列表
├── Dockerfile           ← 告诉 Docker 怎么构建你的应用
├── docker-compose.yml   ← 告诉 Docker 怎么运行所有服务
└── ...其他文件
```

### 1.2 你现在是怎么运行的？（理解现在的状态）

```
你现在（不用 Docker）：
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  终端1：                                                      │
│  $ python main.py           → FastAPI 起在 :8000             │
│                                                              │
│  终端2：                                                      │
│  $ streamlit run main_web.py → Streamlit 起在 :8501          │
│                                                              │
│  浏览器访问：                                                 │
│  http://localhost:8501     → 看到网页界面                      │
│                                                              │
│  已有的 Milvus：                                              │
│  docker ps → 能看到 milvus-standalone 容器在跑                │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 部署到 Docker 之后是什么样子？

```
部署之后（用 Docker）：
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  一条命令启动所有东西：                                       │
│  $ docker-compose up -d                                      │
│                                                              │
│  Docker 自动启动：                                            │
│  - app 容器（包含 FastAPI + Streamlit）                       │
│  - milvus 容器（已经有了，会复用）                            │
│                                                              │
│  浏览器访问（一样的方式）：                                   │
│  http://localhost:8501                                       │
│                                                              │
│  停止所有东西：                                               │
│  $ docker-compose down                                       │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**核心好处**：
- 不用开两个终端
- 不用手动启动每个服务
- 一条命令搞定一切

---

## 第二章：检查你的文件（准备工作）

### 2.1 查看项目里有没有这些文件

打开命令提示符，进入项目目录：

```
cd D:\PythonProject\ragmi
```

然后查看文件：

```
dir
```

你应该能看到这些（关键的）：

```
2026/05/xx  <DIR>          .
2026/05/xx  <DIR>          ..
...
2026/05/xx           1234  Dockerfile              ← 有
2026/05/xx           5678  docker-compose.yml      ← 有
2026/05/xx            890  requirements.txt        ← 有
...
```

**如果看不到 Dockerfile 或 docker-compose.yml**，说明项目还没创建这些文件。按上一轮对话的内容，它们应该已经存在了。

### 2.2 查看你的 Milvus 是不是在跑

```
docker ps
```

你应该能看到：

```
CONTAINER ID   IMAGE                    COMMAND                  STATUS
a1b2c3d4e5f6   milvusdb/milvus:v2.6.16  "/tini -- /milvus/bi..."   Up 2 minutes
```

**如果 milvus 没在跑**：

```
docker-compose -f docker-compose-offline.yml up -d
```

等待 90 秒，然后验证：

```
curl http://localhost:9091/healthz
```

应该返回：

```
{"status":"OK"}
```

---

## 第三章：理解 Docker 和 Docker Compose 的关系

### 3.1 一句话解释

```
Docker = 集装箱标准（让软件在任何地方都能跑）
Docker Compose = 批量管理多个集装箱的工具
```

### 3.2 类比

```
你现在的情况：
- 有一家餐厅
- 需要后厨（FastAPI）、前台（Streamlit）、仓库（Milvus）

不用 Docker（手动管理）：
- 后厨自己管火（python main.py）
- 前台自己管客人（streamlit run）
- 仓库自己管库存（docker run milvus）
- 三个东西要分别启动、分别管理

用 Docker Compose：
- 写一个菜单（docker-compose.yml）
- 说清楚有哪些东西、后厨在哪、前台在哪
- 一条命令（docker-compose up）全部启动
- 一条命令（docker-compose down）全部停止
```

### 3.3 你的两个关键文件

```
┌────────────────────────────────────────────────────────────────┐
│  Dockerfile                                                     │
│                                                                │
│  问：这是什么？                                                 │
│  答：构建手册，告诉我怎么把你的 Python 应用打包成"镜像"         │
│                                                                │
│  就像：食谱，告诉我做这个菜需要什么材料、几步完成                │
│                                                                │
│  你项目里有：                                                  │
│  FROM python:3.11-slim          # 用什么基础镜像               │
│  COPY requirements.txt .        # 复制依赖文件                 │
│  RUN pip install ...            # 安装依赖                     │
│  COPY . .                       # 复制代码                    │
│  CMD ["uvicorn", ...]           # 怎么启动                     │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  docker-compose.yml                                            │
│                                                                │
│  问：这是什么？                                                 │
│  答：运行手册，告诉我启动时要有哪些"服务"，怎么连接              │
│                                                                │
│  就像：餐厅布局图，告诉我后厨在哪个房间、前台在哪个房间           │
│                                                                │
│  你项目里有：                                                  │
│  services:                            # 有哪些服务              │
│    app:                               #   服务1：你的应用        │
│      build: .                        #     从当前目录构建      │
│      ports: ["8000:8000", "8501:8501"]  #  端口映射            │
│      depends_on: [milvus]            #     等 milvus 启动       │
│    milvus:                           #   服务2：向量数据库     │
│      image: milvusdb/milvus:v2.6.16  #     用官方镜像          │
│      ports: ["19530:19530"]          #     端口映射             │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 第四章：开始部署（一步一步来）

### 4.1 第一步：确保 Milvus 在跑

```bash
# 查看当前状态
docker ps
```

**如果 milvus-standalone 容器不在列表里**，执行：

```bash
docker-compose -f docker-compose-offline.yml up -d
```

等待 90 秒，然后：

```bash
curl http://localhost:9091/healthz
```

看到 `{"status":"OK"}` 后继续。

### 4.2 第二步：向量化你的文档

**为什么要做这一步？**
```
用户问问题 → 系统需要搜索相关文档 → 需要先有向量数据
Milvus 存的是向量，不是原始文本
所以要先"向量化"文档，存进去
```

**执行：**

```bash
cd D:\PythonProject\ragmi
set PYTHONPATH=.  && python -m utils.txt_spliter.vector_main
```

（Windows 上用 `set PYTHONPATH=.`，Mac/Linux 用 `export PYTHONPATH=.`）

**看到类似这样的输出**：
```
找到 13 个txt文件
Embedding 维度: 1024
创建集合: txt_data
正在为 1429 个文档片段生成 embedding...
生成 1429 个向量
已插入 100/1429 个片段
...
已插入 1429 个片段
正在创建索引...
正在加载集合...
Milvus 向量库创建成功！
文档片段数: 1429
```

**成功！** 现在 Milvus 里有数据了。

### 4.3 第三步：构建并启动所有服务

这是关键的一步！

```bash
docker-compose up -d
```

你会看到类似这样的输出：

```
[+] Building 14.0s
[+] Running 3/3
 - app    Built          # 1. 构建 app 镜像
 - milvus  running       # 2. 启动 milvus（如果没在跑）
 - app    started        # 3. 启动 app
```

### 4.4 第四步：验证服务都跑起来了

```bash
docker ps
```

你应该看到：

```
CONTAINER ID   IMAGE                    STATUS         PORTS
a1b2c3d4e5f6   milvusdb/milvus:v2.6.16  Up 2 minutes   0.0.0.0:19530->19530/tcp
f6e5d4c3b2a1   docker-ragmi-app         Up 10 seconds  0.0.0.0:8000->8000/tcp, 0.0.0.0:8501->8501/tcp
```

**PORTS 列说明**：
```
0.0.0.0:8000->8000/tcp   → 宿主机8000映射到容器8000
0.0.0.0:8501->8501/tcp   → 宿主机8501映射到容器8501
0.0.0.0:19530->19530/tcp → 宿主机19530映射到容器19530
```

### 4.5 第五步：测试访问

打开浏览器（Chrome/Edge/Firefox），依次访问：

**1. 测试 Streamlit 前端（你应该看到的网页界面）**

```
http://localhost:8501
```

你应该能看到 RAGMI 的聊天界面。

**2. 测试 FastAPI 后端（这是 API 接口）**

```
http://localhost:8000/docs
```

你应该能看到 FastAPI 的 API 文档页面（Swagger UI）。

**3. 测试 Milvus 健康检查**

```
http://localhost:9091/healthz
```

应该返回：`{"status":"OK"}`

---

## 第五章：停止和重启

### 5.1 停止所有服务

```bash
docker-compose down
```

**注意**：这只会停止容器，不会删除数据（Milvus 数据在 volume 里）。

### 5.2 重启所有服务

```bash
docker-compose down
docker-compose up -d
```

或者直接：

```bash
docker-compose restart
```

### 5.3 每次修改代码后重新构建

如果你修改了 Python 代码（main.py, main_web.py 等）：

```bash
# 重新构建镜像（应用新代码）
docker-compose build

# 重启服务
docker-compose up -d
```

或者一条命令搞定：

```bash
docker-compose up -d --build
```

---

## 第六章：常见问题排查

### 问题 1：端口被占用

**错误信息**：
```
Bind for 0.0.0.0:8501 failed: port is already allocated
```

**原因**：8501 端口已经被其他程序占用（可能是之前手动启动的 Streamlit）

**解决方法**：

```bash
# 方法1：关闭占用端口的程序
# Windows 上查看占用端口
netstat -ano | findstr :8501

# 方法2：改 docker-compose.yml 里的端口映射
# 把 "8501:8501" 改成 "8502:8501"
ports:
  - "8502:8501"    # 宿主机8502映射到容器8501
```

然后重新启动：

```bash
docker-compose down
docker-compose up -d
```

访问 `http://localhost:8502`

### 问题 2：Milvus 连接失败

**错误信息**：
```
Connection refused: cannot connect to Milvus
```

**排查步骤**：

```bash
# 1. 检查 Milvus 容器有没有在跑
docker ps | grep milvus

# 2. 如果没跑，启动它
docker-compose -f docker-compose-offline.yml up -d

# 3. 检查 Milvus 健康状态
curl http://localhost:9091/healthz

# 4. 检查端口是否可达
telnet localhost 19530
```

### 问题 3：向量搜索没结果

**原因**：Milvus 里没有数据（没有向量化文档）

**解决方法**：

```bash
# 重新向量化文档
cd D:\PythonProject\ragmi
set PYTHONPATH=.
python -m utils.txt_spliter.vector_main
```

---

## 第七章：命令速查表

```
┌─────────────────────────────────────────────────────────────────┐
│                        常用命令                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  启动所有服务（第一次或每次开机）：                               │
│  docker-compose up -d                                           │
│                                                                 │
│  停止所有服务：                                                  │
│  docker-compose down                                            │
│                                                                 │
│  查看运行状态：                                                  │
│  docker ps                                                       │
│                                                                 │
│  查看日志（实时）：                                              │
│  docker logs -f docker-ragmi-app                                 │
│                                                                 │
│  进入容器内部：                                                  │
│  docker exec -it docker-ragmi-app bash                           │
│                                                                 │
│  重启某个服务：                                                  │
│  docker-compose restart app                                      │
│                                                                 │
│  重新构建镜像（代码改了）：                                      │
│  docker-compose up -d --build                                    │
│                                                                 │
│  向量化文档：                                                    │
│  set PYTHONPATH=. && python -m utils.txt_spliter.vector_main    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 第八章：完整的部署流程（总结）

```
┌─────────────────────────────────────────────────────────────────┐
│                    完整部署流程                                  │
│                                                                 │
│  1. 确保 Docker 在运行                                          │
│     docker ps                                                    │
│                                                                 │
│  2. 确保 Milvus 在运行                                          │
│     docker-compose -f docker-compose-offline.yml up -d           │
│     curl http://localhost:9091/healthz                           │
│                                                                 │
│  3. 向量化文档（如果还没做）                                      │
│     set PYTHONPATH=. && python -m utils.txt_spliter.vector_main │
│                                                                 │
│  4. 启动所有服务                                                 │
│     docker-compose up -d                                        │
│                                                                 │
│  5. 验证                                                         │
│     浏览器打开 http://localhost:8501                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 第九章：下一步（可选）

### 9.1 如果你想加 Redis 缓存

编辑 `docker-compose.yml`，在 `services:` 下添加：

```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis-data:/data
```

然后：

```bash
docker-compose up -d redis
```

### 9.2 如果你想看完整架构图

查看文档 `docs/mettings/Docker-Milvus-Explained.md`

---

**教程结束！有问题随时问。**
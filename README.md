# RAGMI - 基于大模型的知识库问答系统

[![GitHub stars](https://img.shields.io/github/stars/Foggy-liu/Ragmi)](https://github.com/Foggy-liu/Ragmi)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

RAGMI 是一个检索增强生成（RAG）+ LangGraph Agent 的个人知识库问答系统。系统支持上传多种格式文档，
自动解析、切分、向量化存入 Milvus，再由 Agent 决定**要不要检索、检索什么、答案够不够好**，
最后带着溯源片段生成回答。

> 项目的工程重点不在"能不能问答"，而在 **Agent 图的可靠性**：循环边界、超时兜底、工具状态可观测、
> 失败语义清晰、崩溃不 500。详见 [LangGraph Agent (v2.2)](#langgraph-agent-v22) 与 [技术亮点](#技术亮点)。

**项目地址**：https://github.com/Foggy-liu/Ragmi

---

## 功能特性

### 三条独立链路

| 入口 | 后端 | 特点 |
|---|---|---|
| `/agent/chat` | LangGraph Agent | **默认**。自主决策是否检索，检索后反思答案质量 |
| `/rag` | 直接 RAG 管线 | 每次必检索，自带会话历史 |
| `/chat` | 直接 LLM 对话 | 纯闲聊，自带会话历史 |

三条链路各有独立实现，不共用会话状态。

### LangGraph Agent (v2.2)

单 Agent、多工具、ReAct 循环 + LLM-as-judge 反思。四节点图：

```text
START → iter
          ├─ 有 tool_calls → tools → iter        （ReAct 循环，上限 MAX_ITER）
          └─ 无 tool_call  → synth
synth → reflect
reflect
  ├─ end        → END
  ├─ rewrite    → synth        （带着 critique 重写）
  ├─ re_iterate → iter         （换个检索词再来一轮）
  └─ 超过 MAX_REFL → 强制 END
```

- **四节点而非三节点**：v2.1 把"决定要不要调工具"和"写最终答案"塞在同一个 agent 节点里，
  两种 LLM 模式互相干扰。v2.2 拆成 `iter`（纯决策，用 `READY` 信号交接）+ `synth`（纯综合）。
- **两个独立计数器**：`iter_count`（上限 `MAX_ITER=3`，reflect 重写/重检索时重置）、
  `reflection_count`（上限 `MAX_REFL=3`，**永不重置**，绝对防死循环）。
  两个刹车管不同的事，缺一不可。
- **反思闭环**：`reflect` 节点用 `with_structured_output` 输出结构化决策
  （`end` / `rewrite` / `re_iterate` + `critique`），不通过就把 critique 喂回 `synth` 重写。
- **工具状态可观测**：每次工具调用写一条 `{tool, status, code, retryable}`，
  key 是**调用 id**而非工具名（同一轮模型常并发调同一个工具，按名字做 key 会互相覆盖）。
- **异常不外泄**：LLM 超时、工具报错、图递归超限，全部兜成可读回复，不返回 HTTP 500。
- **Debug 元数据**：返回 `{answer, iter_count, reflection_count, tool_called, last_action}`。

详见 [docs/status/项目现状.md](docs/status/项目现状.md)。

### 三层超时机制

职责不重叠的三层，全部配置化（改 `configs/agent_config.yaml` 即可）：

```text
第 1 层  异常归一化    agent/errors.py
         AgentError / AgentTimeoutError（可重试） / AgentToolError（不可重试）

第 2 层  单次动作超时  agent/timeout.py :: Timer
         Tool 30s · LLM 30s

第 3 层  整图总时限    state["deadline"] + is_expired()
         Total 90s，每个节点动手前协作式自检，超时就地收手
```

### 多模型支持

Ollama（本地）/ 阿里云百炼 / MiniMax / 任意 OpenAI 兼容端点。
YAML 配置 + `.env` 占位符，运行时 `switch_model()` 动态切换，无需重启服务。

> Agent 三个 LLM 节点**显式指定** `MiniMax-M3.1-Flash`，与全局默认模型解耦——
> 改 YAML 默认模型不会影响 Agent 走哪个模型。

### Milvus 向量检索

Docker 部署，不占本地内存。Embedding 用 `bge-m3`（1024 维），余弦相似度 + Top-5 召回。
索引构建走**时间戳 collection + 别名原子切换**，新旧共存，可回滚。

### 智能文本切分

两阶段：LangChain 机械切分 → 小片段智能合并（< 80 字符的碎片并入下一块，上限 300 字符），避免语义碎片化。

> 切分参数的**唯一来源**是 `configs/model_config.yaml` 的 `EMBEDDING_CONFIG.text_splitter`
> （`chunk_size: 300` / `chunk_overlap: 30`），由 `utils/txt_spliter/spliter.py` 读取。
> **改 YAML 会生效** —— `test/test_splitter.py::test_s6_default_comes_from_yaml` 钉着这一点。

---

## 技术架构

```text
用户
  ↓  Streamlit 前端（8501）—— 三个页面
FastAPI 后端（8000）
  │
  ├── /agent/chat ──→ LangGraph Agent 图 ──→ 4 个 LLM 节点 + 4 个工具
  │                          │
  │                          └── rag_search → Milvus → bge-m3
  │
  ├── /rag ──────────→ 检索 + grounded prompt → LLM
  ├── /chat ─────────→ 纯 LLM 对话
  └── /api/* ─────────→ 文档上传 → 解析 → 切分 → 向量化 → Milvus

模型平台：Ollama / 阿里云百炼 / MiniMax / OpenAI 兼容
```

### 项目目录

```text
ragmi/
├── api/                       # FastAPI 接口层
│   ├── api_agent.py           # /agent/chat
│   ├── api_chat.py            # /chat
│   ├── api_rag.py             # /rag
│   ├── api_file.py            # 挂载在 /api（上传 + 解析）
│   ├── api_model.py           # 模型切换 / 查询
│   └── dependencies.py        # 依赖注入
├── agent/                     # LangGraph Agent 核心
│   ├── graph.py               # StateGraph 装配（4 节点 + 2 条件边）
│   ├── runtime.py             # 统一入口 ask() + 异常兜底 + recursion_limit 推导
│   ├── state.py               # AgentState 9 字段 + 3 个 reducer
│   ├── constants.py           # 从 YAML 加载 MAX_ITER / MAX_REFL / 超时预算
│   ├── errors.py              # AgentError / AgentTimeoutError / AgentToolError
│   ├── timeout.py             # Timer（单次动作超时）+ is_expired（整图时限）
│   ├── llm_wrapper.py
│   ├── nodes/
│   │   ├── iter_node.py       # 决策：要不要调工具
│   │   ├── synth_node.py      # 综合：把素材写成答案
│   │   ├── reflect_node.py    # 反思：end / rewrite / re_iterate
│   │   ├── should_continue.py # 2 个条件边函数
│   │   ├── material.py        # collect_round_material()：统一取本轮素材
│   │   └── status_tool_wrapper.py  # 官方 wrap_tool_call 钩子：写 tool_status
│   ├── tools/                 # rag_search / calculator / weather / web_search
│   └── prompts/               # iter / synth / reflect / system 四套提示词
├── core/
│   ├── chat/chat.py           # 直接对话业务
│   └── rags/rags.py           # RAG 业务（Milvus 检索 + grounded prompt）
├── utils/
│   ├── docs/                  # 文档扫描 / 清洗 / 解析（md / pdf / word）
│   ├── models/                # 模型管理 + embedding
│   ├── message/               # 会话历史
│   ├── txt_spliter/           # 切分 + vector_main.py（建索引 + 别名切换）
│   └── logging.py
├── web_page/                  # Streamlit 三个页面
├── test/
│   ├── test_agent_timeout.py      # 超时与异常机制（11 用例）
│   ├── test_main_routes_covered.py # 路由挂载回归（AST 扫描）
│   ├── test_agent_flow.py         # L2 Agent 流程层（假 LLM + 假检索）
│   ├── test_api_contract.py       # L3 API 契约层（TestClient）
│   ├── test_tools.py              # L2 工具层（AST 白名单 + 异常归一化）
│   ├── test_rag_model.py          # L2 检索层（检索失败 ≠ 检索为空）
│   ├── test_splitter.py           # L2 切分层（纯函数）
│   ├── test_eval_smoke.py         # L4 真环境冒烟（slow）
│   ├── test_vector_split.py       # vector_split() 端到端（slow）
│   ├── conftest.py + helpers.py + fake_backend.py  # 公共工具层（假 LLM/假检索/假后端）
│   ├── e2e/                       # L4 浏览器层（Playwright，标 e2e）
│   ├── eval/                      # 离线工具路由评估（非 pytest）
│   │   ├── run_agent_eval.py      #   跑 12 个 case 出路由准确率
│   │   └── data/                  #   评估集 + 最新跑分快照
│   ├── eval_quality/              # 答案质量评估（非 pytest，线 A 端到端 + 线 B 反思消融）
│   └── probes/ + archive/         # 过时脚本与一次性探针（**只留本地，不上传仓**）
├── configs/
│   ├── agent_config.yaml      # MAX_ITER / MAX_REFL / timeout.{llm,tool,total}
│   └── model_config.yaml      # 平台 / 模型默认值 / 切分 / Milvus
├── docs/                      # 设计与笔记（详见 docs/README.md）
├── main.py                    # FastAPI 入口
├── main_web.py                # Streamlit 入口
├── docker-compose.yml
└── requirements.txt
```

### 想读懂这份代码？

| 想知道 | 看哪份 |
|---|---|
| 代码怎么串起来的、按什么顺序读 | [`docs/status/项目全景图.md`](./docs/status/项目全景图.md) —— 30 分钟阅读顺序 + 两条数据流 + 14 条不能破的不变量 + 风险地图 |
| 这项目**能做到什么程度** | [`docs/status/项目能力与边界.md`](./docs/status/项目能力与边界.md) —— 已做到的 12 条（带实测证据）/ 量化上限 / 明确做不到的 10 条 / 生产化还差几项 |
| 现在有什么洞、下一步做什么 | [`docs/status/项目现状.md`](./docs/status/项目现状.md) —— §8 是 P0–P3 问题清单 |
| 测试到底测了什么 | [`docs/status/测试现状.md`](./docs/status/测试现状.md) + [`test/README.md`](./test/README.md) |

---

## 快速开始

**环境要求**：Python 3.11+ · Docker + Docker Compose ·（可选）Ollama

### 1. 启动 Milvus

Milvus 服务已经写在 `docker-compose.yml` 里（`milvusdb/milvus:standalone`），
**没有单独的 `docker-compose-milvus.yml` 文件**：

```bash
docker-compose up -d milvus
# Milvus 需要约 90 秒才健康
curl http://localhost:9091/healthz
```

### 2. 安装依赖 + 配置环境变量

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 API 密钥
```

```bash
# MiniMax
MINIMAX_API_KEY=your_key
MINIMAX_BASE_URL=https://api.minimax.com/v1
# 阿里云百炼
ALIYUN_API_KEY=your_key
ALIYUN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# Milvus
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
```

### 3. 向量化文档

```bash
python -m utils.txt_spliter.vector_main
```

> ⚠️ 必须用 `-m`（或先 `export PYTHONPATH=.`）。直接 `python utils/txt_spliter/vector_main.py`
> 会把 `utils/txt_spliter/` 当成 `sys.path[0]`，`import utils.*` 直接
> `ModuleNotFoundError: No module named 'utils'`。

解析后的文件放 `txt/`，原始文件放 `documents/`。脚本会建时间戳 collection → 灌数据 → 建索引 →
**原子切换别名**，旧 collection 保留以便回滚。

### 4. 启动服务

```bash
# 终端 1：FastAPI 后端
python main.py
# 终端 2：Streamlit 前端
streamlit run main_web.py
```

打开 http://localhost:8501。后端健康检查：`curl http://localhost:8000/debug/simple`。

---

## Docker 部署

```bash
# 一键：3 个服务（milvus + api + web）
docker-compose up -d --build

# 或分开
docker-compose up -d milvus    # Milvus（健康检查约 90 秒）
docker-compose up -d api       # FastAPI 后端 :8000
docker-compose up -d web       # Streamlit 前端 :8501
```

- `api` 与 `web` **共用同一个镜像** `ragmi-app:local`（`web` 只换 command，不再每次启动 `pip install`）。
- ⚠️ `api` 服务用 `build`（代码烤进镜像），**改代码后必须 rebuild 才生效**：
  `docker compose up -d --build api`；`web` 是 bind-mount，改完立即生效。
- **Ollama 跑在宿主机上**（compose 里没有 ollama 服务）。容器通过 `host.docker.internal:11434` 访问它，
  地址由 compose 的 `OLLAMA_BASE_URL` 给出；裸跑时用 `.env` 里的 `http://127.0.0.1:11434/v1`。
- **Milvus 只认 `uri`**：`pymilvus 2.6` 的 `MilvusClient(host=..., port=...)` 会**静默忽略** host/port，
  实际连默认的 `localhost:19530`。宿主机上碰巧能用，**容器里必失败**。一律写
  `MilvusClient(uri=f"http://{host}:{port}")`。
- **`requirements.txt` 是全锁文件**（139 包，闭包按 linux 标记求）：只锁直接依赖时传递依赖会漂到新版本
  → 容器 ImportError。改依赖先改「直接依赖」段再重解闭包，**别手改锁定区**。
- 后端探活：`curl http://localhost:8000/debug/simple`。
  ⚠️ 若宿主机上还跑着裸跑后端（监听 `127.0.0.1:8000`），`localhost:8000` 会打到**它**而不是容器 ——
  测容器请用宿主机 LAN IP，并对照容器的 uvicorn access log 确认。

---

## 技术亮点

### 1. 图的循环预算被显式推导，而不是靠运气

LangGraph 默认 `recursion_limit=25`。v2.2 的两个计数器**单独看都安全，叠起来会超**：

- 一轮 `re_iterate` = `iter/tools` 交替最多 `2*MAX_ITER` 步 + `synth` + `reflect` = **8 步**
- `reflect` 最多被调用 `MAX_REFL+1 = 4` 次
- 最坏 = 8 × 4 = **32 步 > 25** → `GraphRecursionError`，被 `ask()` 的 except 吞成"agent 调用异常"

修法不是写死数字，而是**从常量推导**：

```python
_STEPS_PER_ROUND = 2 * MAX_ITER + 2
RECURSION_LIMIT = _STEPS_PER_ROUND * (MAX_REFL + 1) + 10   # = 42
```

以后改 `MAX_ITER` / `MAX_REFL` 不会再撞默认上限。

### 2. 用官方钩子而不是继承改内部方法

工具状态需要拦截每次调用。**继承 `ToolNode` 重写 `__call__` 是死代码**——
LangGraph 走 `node.invoke()` → `self.func`，子类重写的 `__call__` 永远不执行。
正解是框架提供的官方拦截点：

```python
tool_node = ToolNode(ALL_TOOLS, wrap_tool_call=status_wrapper)
```

不继承、不碰内部实现、不受参数名约束，返回 `Command(update=...)` 就能写任意 state 字段。

### 3. 工具状态按调用 id 存，不按工具名存

同一轮里 MiniMax 常并发调 2~3 个 `rag_search`。按工具名做 key，后一次调用会**覆盖**前一次的状态
（实测：成功的那条被 timeout 冲掉）。改用模型生成的调用 id 后，实测 5 次调用 → 5 条状态。

失败时 ToolMessage 的内容是**结构化 JSON 载荷**，不是中文散文：

```json
{"code": "TOOL_TIMEOUT", "status": "timeout", "retryable": true, "message": "调用超时：..."}
```

成功时内容保持原样（原始检索片段），不做包装——最终答案由 Agent 的 LLM 综合。

### 4. 超时是三层协作，不是一层硬杀

- **异常归一化只做一次**，在工具内部翻译成自家异常，下游不再重复翻译
- **Python 杀不掉线程**（没有 `Thread.terminate()`），超时只能"不再等"，底层线程仍会跑完并占连接
  → 不用"外层包 `graph.invoke`"的写法（会留僵尸线程），而是**协作式**：每个节点动手前自检 `deadline`
- **`deadline` 放 state 不放全局变量**：state 每次 invoke 天然隔离，并发请求不串味
- **`.with_config({"timeout": N})` 是死代码**——`langchain_core` 全包从不读 `RunnableConfig["timeout"]`，
  超时只能在**构造时**传：`ChatOpenAI(..., timeout=30)`

### 5. 工具调用不悬空

LangGraph 的 `should_continue` 若在 `iter_count >= MAX_ITER` 时**先**判上限就返回，
第 3 轮决策发出的 `tool_calls` 永远不会被执行 → 留下"有 tool_calls 但没 ToolMessage"的 AIMessage。
MiniMax 收到这种消息会直接 **HTTP 400**（`invalid params, tool call and result not match`）。

修法是把边界判断改成 `iter_count + 1 >= MAX_ITER`——`iter_count` 是"已跑过几次"，
本次调用之后才达到上限。改完实测悬空数 **2/7 → 0/5**，顺带省掉一次白跑的 LLM 调用。

### 6. 路由挂载回归测试

用 AST 扫描 `api/*.py` + `main.py`，自动检测"写了路由模块但忘了挂载"的死代码。
历史教训：曾经的 `/vector` 接口就是这么消失的（404 才发现）。见 `test/test_main_routes_covered.py`。

---

## 评估结果

> **诚实说明**：12-case 评估集本身是 v1 时代设计（`expected_tool` 只有 chat/rag 二值，
> 没跟上 v2.2 的 4 个工具），在 `test/eval/data/agent_test_cases.json`。
> 评估脚本 2026-11-18 修好四处失效后重新实跑，结果如下 —— **评估集口径待修，但数字是真的**。

历史数据（MiniMax + Milvus 实测）：

| 指标 | v1 baseline | v2 baseline | v2.1 (with Reflection) | **v2.2（2026-11-18 实测）** |
|------|------------|-------------|------------------------|---------------------------|
| 总准确率 | 75% | 92% | 91.7%（持平） | **75.0%（9/12）** |
| RAG 类 | — | 80% (4/5) | 80% (4/5) | 80% (4/5) |
| Chat 类 | — | 100% (7/7) | 100% (7/7) | 71.4% (5/7) |
| **稳定性（0 异常）** | — | — | — | **12/12 = 100%** |
| 反思最终决策 | — | — | — | 全部 `end`（12/12） |
| 反思轮数分布 | — | — | — | 1 轮 ×10 / 2 轮 ×2 |
| 工具调用总次数 | — | — | — | 21 次，**全部 `success`** |
| 单 case 中位耗时 | 48.28 秒 | — | — | **25.79 秒** |

**2026-11-15 是 83.3%（10/12），2026-11-18 是 75.0%（9/12）** —— 差异**全部来自 T07 一次翻转**
（"Python 的 list 和 tuple 有什么区别"该不该检索）。**LLM 路由本身有随机性**，
所以这两个数都是**单次采样**，不能当基线用。要真基线得重建评估集 + 接 CI（见"后续规划"）。

**评估脚本本身修过 4 个 bug**（2026-11-18），最要命的是**路由判定**：老脚本把"调了任何工具"
都记成 `rag`，于是 T02 实际调 `calculator`、T09 实际调 `weather` 被误判成错（脚本口径 66.7%）。
现在改成直接看 `AIMessage.tool_calls` 里的工具名，这两个 case 判回正确。真正错的只剩 3 个：

| Case | 期望 | 实际 | 结论 |
|---|---|---|---|
| T06 `RAG 的核心定义是什么` | rag | 无工具 | ❌ 真错：该检索却没检索 |
| T07 `Python 的 list 和 tuple 有什么区别` | chat | `rag_search` ×2 + `web_search` | ❌ 真错：不该检索却检索，还调了占位工具 `web_search`（耗时 70 秒） |
| T10 `介绍下 LangGraph` | chat | `rag_search` ×3 | ❌ 真错：不该检索却检索 3 轮，`iter_count` 打满上限（耗时 83 秒） |

**结论（与 v2.1 同一个诚实结论）**：反思机制**不提升路由准确率**，T06 这类路由错误事后修不了。
v2.2 的价值在别处 —— 稳定性从"会抛异常"变成 12/12 零异常、`tool_calls` 悬空从 2/7 降到 0、
工具状态可观测。**这个诚实结论比一个好看的数字更有价值**——它证明了反思的边界在哪。

---

## 运行测试

```bash
pytest -m "not slow and not e2e" -v   # 快回归（90 条，不调真 LLM、不开浏览器）
pytest -m e2e -v --tracing=retain-on-failure   # 浏览器层（Playwright + 专用 Streamlit:8511）
pytest -m slow -v                     # 真环境（真 MiniMax + 真 Milvus，慢且花钱）
pytest -v                             # 全量（112 个收集项）
```

> ⚠️ **快回归的耗时依赖 Milvus 在不在**（2026-11-25 在 99 条用例上实测）：
> **Milvus 不可达 → 108.70 秒**；**Milvus 在线 → 7.5–8.9 秒**（连续 6 次实测：
> 8.89 / 7.49 / 7.60 / 7.89 / 7.83 / 7.72 秒）。慢的不是用例，是
> **`test_api_contract.py` 的 12 个 setup** ——
> Milvus 不通时每个 ~11 秒，因为 `main.py` 的 lifespan 启动时会连一次 Milvus 探活
> （`MilvusClient.list_collections()`），**这次探活要阻塞约 10–11 秒**（实测），
> 而 `TestClient` 每个用例都重新触发一次 lifespan。
> Milvus 在线时探活瞬时返回，每个 setup 只花 ~0.55 秒（其中 `OllamaEmbeddings()` 构造
> —— httpx 客户端 + SSL 上下文 —— 占 0.46 秒）→ 12 × 0.55 ≈ 6.7 秒，其余 87 条只要 1.43 秒。
>
> ⚠️ **这个数对机器负载敏感**：同一天在刚跑完索引重建 + Docker 镜像重建（机器满载）时
> 测到 **19.3–21.3 秒**，缓下来后回到 7.5–8.9 秒。**不是代码改动或嵌入模型切换造成的** ——
> 两个候选解释已实测排除：① Ollama 模型冷/热无差别（卸载 bge-m3 后 7.83 秒 vs 热跑 7.72 秒）；
> ② `import main` 不是元凶（`OllamaEmbeddings()` 构造：裸进程 0.46 秒、import 后 0.48 秒）。

**4 层测试体系**（2026-11-16 落地，2026-11-17 清零 xfail + 加工具层与检索层）。详见 [`docs/status/测试体系.md`](./docs/status/测试体系.md)。

| 层 | 文件 | 测什么 | 条数 | 实测 |
|---|---|---|---|---|
| L2 流程 | `test/test_agent_flow.py` | 跑**真的 LangGraph 图**（假 LLM 剧本 + 假检索）：工具 4 态、两个循环刹车、三种超时时机、`ask()` 契约 | 17（+9 参数化不变式） | 26 passed |
| L3 契约 | `test/test_api_contract.py` | `TestClient`：接口字段形状、缺字段 422、模型切换、上传路径穿越 / 类型白名单 / 同名覆盖、依赖单例 | 12 | 12 passed |
| L2 工具 | `test/test_tools.py` | `calculator` 的 AST 白名单求值（**P1-2** 回归护栏）+ `rag_search` 的异常归一化（**P2-7**） | 26 | 26 passed |
| L2 检索 | `test/test_rag_model.py` | **"检索失败"和"检索为空"分得开吗**（**P2-7** 的回归护栏） | 7 | 7 passed |
| L2 切分 | `test/test_splitter.py` | 纯函数切分：无内容丢失、块长上限、默认参数来自 YAML | 6 | 6 passed |
| L4 浏览器 | `test/e2e/test_browser_e2e.py` | 进程外假后端 + 专用 Streamlit：发问 / 清空 / 上传统计 / 三页互切 / 后端 500 | 8 | 8 passed |
| L4 冒烟 | `test/test_eval_smoke.py` | 真 MiniMax + 真 Milvus：算式必调工具、检索路由、工具失败不失控 | 4 | 4 passed（74.17 秒） |
| 既有 | `test/test_agent_timeout.py` + `test_main_routes_covered.py` | 工具状态 4 态 / Timer / deadline / 路由挂载 | 13 | 13 passed |
| 既有（慢） | `test/test_vector_split.py` | 摄取全链路 → 原子切 alias | 1 | passed（25 分 29 秒） |

**`xfail` 已清零（2026-11-17）** —— 曾用 `xfail(strict=True)` 固化的 3 个缺陷全部修掉：
F9a_x（超时兜底把内部占位当答案）、S5（`Splitter(max_chars)` 没生效，**P1-7**）、
E4（**P1-1** `/rag` 字段名不匹配）。另修 **P1-2**（`calculator` 的 `eval()` RCE）。
现在快回归 **99 passed / 0 xfailed**（2026-11-25 实测）。

**代码覆盖率（实测 2026-11-22，`pytest --cov=.`）**：`agent/` **91%**、全项目 **56%**。
低覆盖集中在**摄取与前端**——`utils/docs/` 11~20%、`web_page/` 0%（Streamlit 页面
只在浏览器 E2E 里被点到，不在 pytest 覆盖范围内）。

**仍然没覆盖的**（别把绿色当成质量保证）：

- **reflect prompt 的"工具失败时不判 `re_iterate`"硬约束** —— 假 reflect 被剧本编排，原理上测不到。
- **评估集口径过时** —— 12-case 评估集的 `expected_tool` 是二值的，跟不上 v2.2 的 4 个工具。
- **真实检索链路**只有 `test_vector_split.py` 那条 25 分钟的慢用例碰到。

### 既有快回归用例具体测什么

（不调真实 LLM，全部是纯逻辑 / AST 静态检查；**但 app lifespan 会探一次 Milvus**，见上面耗时说明）

`test/test_agent_timeout.py` —— 11 个：

| # | 用例 | 测什么 |
|---|---|---|
| 1 | `test_tool_status_success` | 工具返回非空 → `status=success` / `code=OK`，且原始内容透传不包装 |
| 2 | `test_tool_status_empty` | 工具返回空串 → `status=empty` / `EMPTY_RESULT`（**不是** success） |
| 3 | `test_tool_status_timeout` | 抛 `AgentTimeoutError` → `status=timeout` / `retryable=true`，**且必须回写 ToolMessage**（漏写会让 MiniMax 报 400），载荷是结构化 JSON |
| 4 | `test_tool_status_error` | 抛 `AgentToolError` → `status=error` / `retryable=false` |
| 5 | `test_timer_turns_slow_call_into_agent_timeout` | `Timer` 超时抛的是 `AgentTimeoutError`，**不是**裸 `TimeoutError`（真实第三方超时异常没有一个继承它） |
| 6 | `test_timer_passes_through_normal_result` | 正常返回时 Timer 不改变结果 |
| 7 | `test_is_expired_uses_deadline` | `deadline` 是绝对时间戳；过期 / 未过期 / 没设 deadline 三种情况 |
| 8 | `test_synth_expired_returns_previous_answer` | 超时时交出 `state["last_answer"]`，**不是**从 messages 里倒着找 AIMessage（那会拿到 `"READY"` 占位消息） |
| 9 | `test_synth_expired_without_previous_answer` | 第一次就超时、没旧答案 → 明确说超时，不留空 |
| 10 | `test_expired_state_routes_to_end` | `expired=True` 时 `should_continue` 和 `after_reflect` **都**返回 `"__end__"` |
| 11 | `test_agent_chat_endpoint_is_not_async` | AST 检查 `agent_chat` 不是 `async def`（同步阻塞写在 `async def` 里会占死事件循环） |

`test/test_main_routes_covered.py` —— 2 个：

| # | 用例 | 测什么 |
|---|---|---|
| 12 | `test_every_router_is_imported_and_mounted` | `api/*.py` 里每个 `APIRouter()` / `FastAPI()` 都必须被 `main.py` import **且** `include_router`/`mount`（防 `/vector` 那种 404 死代码） |
| 13 | `test_no_orphan_router_import` | 反向检查：没有"import 了却不挂载"的孤儿 router |

**这 13 个用例没有覆盖什么**（别当成质量保证）：

- **Agent 图的路由逻辑** —— 已由 `test/test_agent_flow.py` 的 17 条独立用例 + 9 条参数化不变式补上，
  但它们跑的是**假 LLM**；真实模型的路由决策由 `test_eval_smoke.py`（slow）抽查。
- **评估集口径过时** —— 12-case 评估集的 `expected_tool` 是二值的，跟不上 v2.2 的 4 个工具。

### 端到端用例（慢，验收用）

| 用例 | 测什么 | 实测结果 |
|---|---|---|
| `test/test_vector_split.py` | 摄取全链路：切分 → embed → 建带时间戳集合 → 插入 → 建索引 → 加载 → **原子切 alias** | ✅ **passed，耗时 25 分 29 秒**（2026-11-16 实测，1667 个片段重新 embed） |

> 这个用例每次跑都要把 `txt/` 下全部文件重新切块并**全量重新 embed**
> （1024 维，CPU；单批 32 块 ≈ 18 秒）。它是**改了摄取链路后跑一次**的验收用例，
> 不该混在 `pytest` 默认流程里 —— 已标 `@pytest.mark.slow`，默认快回归会跳过它。
>
> ⚠️ 上面 25 分 29 秒是 **2026-11-16** 的实测（当时 33 个文件 / 1667 块 / bge-large）。
> 2026-11-25 语料清理成 **17 个文件 / 1517 块 / bge-m3** 后，同一条链路由
> `python -m utils.txt_spliter.vector_main` 重跑实测 **14 分 20 秒**（14:50:54 → 15:05:14）。

### 离线评估、探针与归档

`test/eval/` 是**离线的工具路由评估**：跑 12 个 case，量工具路由准确率 + 稳定性
（结果见上文"评估结果"），跑法见 [`test/eval/README.md`](./test/eval/README.md)。

`test/eval_quality/` 是**离线的答案质量评估**（2026-11-27 新增，与上面那条**完全隔离**）：
线 A 端到端量"答得好不好"（12 题 × 3 遍，总分 0.9333），线 B 量"反思节点判得准不准"
（48 格 × 3 遍，真阳性率 100%、改后改善率真·坏答案 +0.51），
跑法见 [`test/eval_quality/README.md`](./test/eval_quality/README.md)。

`test/probes/` 是**手动探针脚本**，`test/archive/` 是**过时测试脚本的只读归档**
（v1/v2.1 的死脚本 + 历史跑分快照）。两者都**已经被 pytest 用例取代** ——
探针发现的 `tool_calls` 悬空 / `tool_status` 覆盖两个 bug，已转成
`test_agent_flow.py` 的 F1b + 公共不变式。

> ⚠️ **这两个目录只留本地，不上传仓**（见 `.gitignore`）—— 里面的脚本一半能跑一半不能，
> 留在仓里只会让人误以为它们是现行测试。活着的那个已迁到 `test/eval/`。

**每个文件的分类、测什么、实测结果** —— 见 [`test/README.md`](./test/README.md)。

---

## 已知限制

诚实列出当前**没做**或**做得不精确**的部分：

- **Agent 没有多轮记忆**：图没有 checkpointer，`thread_id` 传了但没人读。
  三个 LLM 节点也从不把 `state["messages"]` 发给 LLM（每次从零拼 prompt）。
  补记忆前要先处理 iter 的占位消息（`"READY"` 等），它们会一起进历史。
- **路由准确率未达标**：75.0%（9/12），低于 90% 的合格线。**LLM 路由本身有随机性**，
  这个数只是单次采样 —— 要真基线得**重建评估集**（现有 12 个 case 的 `expected_tool`
  还是 v1 的二值口径，跟不上 v2.2 的 4 个工具）+ **接 CI**。
- **`retryable` 还不能细分**：工具层只拿到 `AgentToolError` 这一个"其他错误"的桶，
  区分不出限流/服务不可用（可重试）与参数错/代码 bug（不可重试）。
- **`/chat` `/rag` 是 `async def` 但内部同步阻塞**：一次请求会占住事件循环直到 LLM 返回。
  `/agent/chat` 早在 v2.2 就用普通 `def` 规避了，这两条老端点没跟进。
  ⚠️ **改它不是"改两行"** —— 改成普通 `def` 会让它们进 FastAPI 线程池，
  `MessageManager.sessions`（无锁）就从"事件循环串行化"变成"多线程无锁访问"，必须连带加锁。
- **索引与检索用不同客户端**：`vector_main.py` 直连 Ollama HTTP，
  查询侧 `core/rags/rags.py` 用 `langchain_ollama`——同一个 embedding 模型，两条路径。
- **CORS 放开所有源**：开发期便利，生产部署应改成白名单。
- **没有鉴权**：任何能访问到 8000 端口的人都能读你的知识库。**不能暴露公网**。

---

## 后续规划

- [x] Milvus 向量库替换 ChromaDB
- [x] Docker 容器化部署
- [x] Self-Reflection 闭环（v2.1）
- [x] Agent 图重构：四节点 + 双计数器（v2.2）
- [x] 三层超时机制 + 异常归一化
- [x] 工具状态结构化 + 悬空修复
- [x] `retrieve()` 契约拆分：区分"空结果"与"检索失败"（2026-11-17，P2-7）
- [x] 切分参数改为从 YAML 读取（2026-11-17，P1-7）
- [x] Ollama embedding 调用加 timeout（2026-11-17，P2-8）
- [ ] **重建评估集**（当前第一优先级）—— 现有 12 个 case 的 `expected_tool` 还是 v1 二值口径
- [ ] **评估接 CI** —— 路由准确率要能自动断言，否则改完不知道有没有变好
- [ ] 多轮记忆（LangGraph checkpointer）—— 需先修 iter 占位消息
- [ ] `/chat` `/rag` 改普通 `def` + `MessageManager` 加锁（并发）
- [ ] 混合检索（向量 + BM25）
- [ ] 用户认证与权限管理

---

## 许可证

MIT License

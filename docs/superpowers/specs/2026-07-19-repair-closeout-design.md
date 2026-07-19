# RAGMI 修复收尾设计

**日期**：2026-07-19
**目标**：把 RAGMI 项目带到"面试官 30 分钟内能跑通、能读懂、能问得下去"的水平

## 背景

RAGMI 是一个基于 RAG + Agent 的个人知识库问答系统。当前项目处于 v2.1（LangGraph 重构完成、reflection 节点集成），但存在大量遗留问题阻碍项目作为面试作品的可信度：

- 后端 Dockerfile 启动模块路径错误
- 4 个 docker-compose 文件互相打架
- 关键上传路径不通（API router 未挂载、配置读取错误）
- 测试存在死代码、矛盾用例、统计水分
- 文档（CLAUDE.md、README.md、STATUS.md）与实际代码严重脱节

## 范围

### 包含

- M1：可运行基线（Docker / requirements / 启动链路）
- M2：上传 → RAG 闭环（路径安全、配置读取、数据安全重建、UI 收口）
- M3：评估与测试可信（修测试、加 Makefile）
- M4：文档与可观测（CLAUDE.md / README / 日志）

### 明确排除（YAGNI）

- 鉴权 / 多用户 / RBAC
- Multi-Agent / 多角色协作
- BM25 / 混合检索
- 持久化多轮记忆
- 完整生产监控（Prometheus / Grafana）
- LLM 调度层重写（MiniMax 当前能用）
- MCP 页面实现（仅清理占位）
- GitHub Actions CI（仅本地 Makefile）

## 设计原则

1. **纵深优先于广度**：每个里程碑独立可验证，前一个不过不下一个
2. **fail-loud > silent fallback**：配置错误必须启动期报错，不掩盖
3. **零数据丢失窗口**：知识库重建必须可回滚
4. **测试可信度 > 测试数量**：宁可少测，不要假数据
5. **演进透明**：保留演进历史（demos 归档、STATUS 归档），不"为了好看清理"

## 架构

### 当前架构（修复前）

```
main_web.py ──┐
              ├──> main:app ──> agent/graph.py ──> tools/{rag,chat}
api_file.py ──┘                  ↑
                                  └──> 错误路径（配置被忽略、router 未挂载）
```

问题：
- `api_file.py` 的 router 未挂入 `main:app`
- `api_file.py` 有路径穿越漏洞
- Milvus 配置读取路径错误（走硬编码 fallback）
- Dockerfile 启动命令错误（指向 `api.api_file:app`）
- 多 docker-compose 文件冲突

### 修复后架构

```
┌──────────────────────────────────────────────────────────┐
│  Streamlit Frontend (main_web.py)                        │
│  - Page 1: Agent 智能问答 (默认页)                        │
│  - Page 2: RAG 知识库问答（直连 RAG，进阶证明）              │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI Backend (main:app, port 8000)                   │
│                                                          │
│  路由（必须全部保留，作为分层证据）:                         │
│    POST /agent/chat    -> Agent 编排（ReAct + 反思）       │
│    POST /rag           -> 直连 RAG（Milvus + Embedding）  │
│    POST /chat          -> 直连 LLM（仅供 curl 验证）       │
│    POST /api/upload-and-parse -> 文件上传解析              │
│    GET  /debug/simple  -> 后端存活探测                    │
│                                                          │
│  lifespan hook: 启动期校验 UPLOAD_DIR、Milvus 探活         │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  Agent Layer (agent/，v2.1 LangGraph)                    │
│  - graph.py: StateGraph (agent → tools → reflect)        │
│  - nodes/: agent_node, tool_node, reflect_node           │
│  - state.py: MAX_ITERS=5, MAX_REFL=1                     │
│  - runtime.py: ask() 入口 + debug metadata               │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  Core Layer                                             │
│  - core/rags/rags.py: RAG pipeline（无硬编码 fallback）    │
│  - utils/models/embedding_model.py: 读 vector_store.milvus│
│  - utils/txt_spliter/vector_main.py: alias swap 重建      │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  Data Layer                                             │
│  - Milvus (alias "langchain" 永远指向当前活跃集合)         │
│  - MessageManager: 会话历史                               │
└──────────────────────────────────────────────────────────┘
```

## 数据流：上传 → 检索

```
1. 用户在 RAG 页面点击上传文件
2. Streamlit → POST /api/upload-and-parse (multipart)
3. api_file.py:
   a. 校验文件名（拒绝 ../ 等路径穿越字符）
   b. 校验 resolve() 后的路径在 UPLOAD_DIR 内
   c. 保存到 UPLOAD_DIR/<safe_filename>
   d. 调 parse_and_chunk() → 切分文本
   e. 调 ingest_to_milvus(chunks) → 写入 alias "langchain"
4. 用户问问题
5. Agent / RAG → Milvus search via alias "langchain"
6. 检索结果 + LLM 生成答案
```

## 数据流：Milvus 重建（alias swap）

```
旧状态：alias "langchain" → collection "langchain_v0"

1. vector_main.py 收到重建指令
2. 创建 collection "langchain_v1_<timestamp>"
3. 灌入所有新 chunks 到 v1
4. 调用 client.alter_alias("langchain", "langchain_v1_<timestamp>")
   - 这是原子操作，毫秒级切换
   - 查询不会失败
5. 旧 collection "langchain_v0" 不删，保留 7 天回滚窗口（v2.2 实现自动清理；本轮由人工在 Milvus 控制台删除）

不变量：应用层只通过 alias "langchain" 访问，永远不直接用集合名
```

## 组件

### M1 改动

| 文件 | 改动 |
|------|------|
| `requirements.txt` | 锁死依赖版本（具体版本号在 M1 实施第一步通过 `pip freeze > requirements.lock` 生成，从 lock 提取主依赖填入 `requirements.txt`） |
| `requirements-dev.txt` | 新建：pytest / pytest-asyncio / pytest-cov / requests |
| `Dockerfile` | CMD 改为 `uvicorn main:app --host 0.0.0.0 --port 8000` |
| `docker-compose.yml` | 3 个 service：milvus、api、web；Ollama 用 `host.docker.internal:11434`（跨平台不处理，Linux 跑不起来是已知限制） |
| `docker-compose-milvus.yml` / `docker-compose-offline.yml` / `compose.yaml` | 删除 |
| `.env.example` | 新建，列 env，标注 compose 内 vs 裸跑的 MILVUS_HOST 差异 |

### M2 改动

| 文件 | 改动 |
|------|------|
| `main.py` | 挂载 `api_file.router`（`prefix="/api"`）；加 lifespan hook 校验 UPLOAD_DIR、Milvus 探活 |
| `api/api_file.py` | 路径穿越校验（`Path.resolve().is_relative_to(UPLOAD_DIR)`），失败返回 400 |
| `utils/models/embedding_model.py` | 改读 `embed_config["vector_store"]["milvus"]`，缺字段 fail-loud |
| `core/rags/rags.py` | 删硬编码 fallback，配置缺失 `raise ConfigError` |
| `utils/txt_spliter/vector_main.py` | 改用 alias swap 重建，保留 7 天回滚窗口 |
| `web_page/knowledge_base.py` | 删除 |
| `web_page/mcp_page.py` | 删除 |
| `main_web.py` | 侧边栏保留两个页面：Agent 问答（默认）、RAG 问答（直连 `/rag`） |

### M3 改动

| 文件 | 改动 |
|------|------|
| `test/test_agent.py` | 删除（v1 死代码） |
| `test/agent_test_cases.json` | T06：`expected_tool` 改 `"chat"`（"什么是 ReAct 模式？" 是通用概念） |
| `test/run_agent_eval.py` | 增加 `status` 字段（`correct` / `wrong_tool` / `exception`）；加 `--mock` 参数走 MockLLM |
| `test/agent_eval_results.json` | 重跑生成，标题含 "Tool Routing Accuracy" |
| `pytest.ini` | testpaths = test |
| `Makefile` | `make test` = pytest + run_agent_eval（mock 模式） |
| `agent/state.py` | 先实测 `reflection_count` 行为再决定改不改 |

### M4 改动

| 文件 | 改动 |
|------|------|
| `CLAUDE.md` | 架构章节重写为 v2.1（LangGraph + 3 nodes + reflection）；删 v1 模块引用；保留 Agent Ecosystem Context |
| `README.md` | 加 "快速启动（Docker）"、"手动启动"、"跑测试" 三个 section |
| `docs/STATUS.md` | 移到 `docs/archive/2026-07-08-pre-v2.1.md`，加 "已冻结，仅供考古" 顶部注释 |
| `agent_demo/` | 不上传到 git（不进 git history） |
| `.gitignore` | 加 `agent_demo/`、`txt/.file_filter.json`、`documents/.tmp/`、`.pytest_cache/` |
| `utils/logging.py` | 新建，统一 `logging.basicConfig` 格式（时间、级别、模块、消息） |
| `agent/runtime.py` / `agent/nodes/*.py` / `core/rags/rags.py` | 核心调度路径 `print()` 换 `logger.info()`；`agent_demo/`、`examples/`、`scripts/`、`if __name__ == "__main__"` 下的调试 print 保留 |

## 错误处理

### M1

- 启动后端时 Milvus 不可达：lifespan 写 error 日志，**不阻塞启动**（开发期可能先起后端再起 Milvus）
- 端口冲突：Docker Compose 启动失败暴露明确错误

### M2

- 上传文件路径穿越：返回 HTTP 400，error message 不暴露服务器路径
- 配置缺失（Milvus host/port/collection）：启动期 raise `ConfigError`，拒绝启动
- 重建中途失败：保留旧 alias 不切换，新 collection 回滚删除

### M3

- `make test` 任意一步失败：非零退出码，CI/手动都能识别
- `run_agent_eval.py` 异常：`status=exception` 单独列出，不算"wrong_tool"

### M4

- 日志统一格式，便于 grep：
  ```
  2026-07-19 14:23:01 INFO agent.runtime ask() entry query="..."
  2026-07-19 14:23:02 INFO agent.nodes.reflect reflection insufficient
  ```

## 测试

### 单元测试

```bash
pytest test/test_reflect.py
```

覆盖：
- `parse_reflection_json` 6 种边界 case（标准 JSON、前后乱码、完全乱码、截断、缺字段、字符串 "false"）
- `reflect_node` 4 种行为（sufficient pass、insufficient 追加 critique、MAX_REFL 强制 pass、garbage fail-safe）

目标：10/10 通过（当前状态）。

### 集成测试

```bash
python test/run_agent_eval.py --mock
```

覆盖：
- 12 个测试用例的 tool routing
- Agent 稳定性（无 exception）
- T06 修正后预期 12/12 = 100%

### 端到端验证（M2）

```bash
# 上传
curl -F "file=@test/fixtures/sample.txt" http://localhost:8000/api/upload-and-parse

# 检索
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "sample.txt 里讲了什么?"}'
```

期望：答案含原文内容。

### Makefile

```makefile
.PHONY: test test-unit test-eval

test: test-unit test-eval

test-unit:
    pytest test/test_reflect.py -v

test-eval:
    python test/run_agent_eval.py --mock
```

## 验证矩阵（每个里程碑的通过标准）

| 里程碑 | 验证命令 | 通过标准 |
|--------|----------|----------|
| M1 | `docker compose up -d && curl http://localhost:8000/debug/simple` | 200 |
| M2 | curl 上传 + curl 检索 | 答案含原文 |
| M3 | `make test` | 10/10 单元 + 12/12 eval |
| M4 | `grep -oE 'agent/[a-z_/]+\.py' CLAUDE.md \| xargs -I{} test -f {}` | 无 MISSING |

## 风险与权衡

### M1

- **风险**：锁死 requirements 版本可能与现有 lockfile 冲突
- **缓解**：先 `pip freeze` 当前能跑的环境，diff 后再写入

### M2

- **风险**：alias swap 在 pymilvus 2.6.14 已确认支持，但回滚窗口的清理任务可能漏跑
- **缓解**：清理任务用 APScheduler 在 lifespan 启动时注册；先记 TODO，v2.2 再实现
- **风险**：删 web_page 文件可能影响其他引用
- **缓解**：删前 `grep -rn "knowledge_base\|mcp_page"` 确认无外部依赖

### M3

- **风险**：T06 改预期后，未来如果加 ReAct 文档到知识库，T06 应该改回 rag
- **缓解**：在测试用例里加注释说明前提条件

### M4

- **风险**：CLAUDE.md 改写可能丢失 Agent Ecosystem Context 等有价值的内容
- **缓解**：仅改架构章节（第 28-86 行），其他章节保留

## 后续（不在本轮范围）

- M5: 真实 LangSmith 评估（当前已集成但未跑）
- M6: MCP 工具接入
- M7: BM25 混合检索
- M8: GitHub Actions CI（如果项目上 GitHub）
- M9: alias 清理定时任务实现（v2.2）

## 面试话术参考

修复完成后可以这样描述：

> "RAGMI 项目我做了 v1 → v2 → v2.1 三次迭代。v1 是手写 ReAct 循环，v2 切到 LangGraph StateGraph，v2.1 加了 reflection 节点做 self-correction。当前的难点不是模型调用，而是工程可靠性——配置文件错误必须启动期报错，知识库重建不能丢数据，测试结果必须可信。"
# test/ 目录说明

> **实测日期：2026-11-15 / 目录整理 + 4 层测试体系落地：2026-11-16 / 债务清零 + 新增工具层：2026-11-17
> / 过时脚本移出版本库 + 离线评估迁到 `test/eval/`：2026-11-22**。
> 下面每一行的"结果"都是实跑出来的，不是推断。
>
> **这个文件是 `test/` 的唯一索引**。当前测试体系的完整设计与落地状态见
> [`../docs/status/测试体系.md`](../docs/status/测试体系.md)（4 层 80 独立用例 / 89 收集项，**已全部落地**），
> 已有测试的实测清点见 [`../docs/status/测试现状.md`](../docs/status/测试现状.md)。

## 一、目录结构

```text
test/
├── test_agent_timeout.py       # 超时与异常机制（11 用例）        ← 生效
├── test_main_routes_covered.py # 路由挂载回归（AST 扫描，2 用例）  ← 生效
├── test_vector_split.py        # vector_split() 端到端（1 用例）   ← 生效，标 slow
├── test_agent_flow.py          # L2 Agent 流程层（26 收集项）      ← 生效（2026-11-16 新增）
├── test_api_contract.py        # L3 API 契约层（12 用例）          ← 生效（2026-11-16 新增）
├── test_splitter.py            # L2 切分层（6 用例）                ← 生效（2026-11-16 新增）
├── test_tools.py               # L2 工具纯函数层（26 用例）        ← 生效（2026-11-17 新增）
├── test_rag_model.py           # L2 RAG 检索语义层（7 用例）       ← 生效（2026-11-17 新增）
├── test_file_filter.py         # L2 入库去重层（9 用例）          ← 生效（2026-11-25 新增）
├── test_eval_smoke.py          # L4 真环境冒烟（4 用例）            ← 生效，标 slow
├── conftest.py                 # 假 LLM / 假检索 / 假后端 fixtures
├── helpers.py                  # 公共工具层（假 LLM 剧本、消息工具）
├── fake_backend.py             # 进程外假后端（浏览器层用）
├── e2e/                        # L4 浏览器层
│   ├── test_browser_e2e.py     #   E1–E8（标 e2e，假后端）
│   ├── real_stack_check.py     #   真栈全接口体检（**非 pytest**，见下）
│   └── _artifacts/             #   真栈产物（截图 + HTML 报告，已 gitignore）
├── eval/                       # 离线工具路由评估（**非 pytest**，唯一活着的离线评估）
│   ├── run_agent_eval.py       #   跑 12 个 case 出路由准确率 + 稳定性
│   ├── data/
│   │   ├── agent_test_cases.json    #   评估集（12 个 case）
│   │   └── agent_eval_results.json  #   最新跑分快照（2026-11-18：75.0% = 9/12）
│   └── README.md               #   跑法 + 数字怎么读
├── probes/                     # 一次性探针脚本（**已 gitignore，不上传仓**）
├── archive/                    # 过时测试脚本的只读归档（**已 gitignore，不上传仓**）
└── fixtures/                   # 手工测试素材（sample.txt 已进版本库）
```

> ⚠️ **`probes/` 与 `archive/` 都不进版本库**（2026-11-22 起）—— 它们的内容已被 pytest 用例
> 取代，留着只会让人误以为是现行测试。**干净 clone 看不到这两个目录**。
> 需要历史脚本时看本地工作区，或 `git log -- test/archive/`。
> 唯一活着的离线评估已从 `archive/scripts/` 迁到 **`eval/`**（2026-11-22）。

**收集规则**（`pytest.ini`）：

```ini
testpaths = test
python_files = test_*.py
norecursedirs = archive probes eval .* build dist node_modules venv __pycache__
```

→ `test/probes/`、`test/archive/`、`test/eval/` **永不收集**。

**marker**：`slow`（需真实 Milvus/Ollama/MiniMax）、`e2e`（浏览器）。

```bash
pytest -m "not slow and not e2e" -v   # 快回归（秒级）
pytest -m e2e -v --tracing=retain-on-failure   # 浏览器（需 Playwright + Chromium）
pytest -m slow -v                     # 慢用例（需 Milvus + Ollama + MiniMax）
pytest -v                             # 全量（含 25 分钟的向量切分）
```

### 新增：4 层测试体系（2026-11-16 落地）

| 类别 | 文件 | 状态 | 说明 |
|---|---|---|---|
| **I · 新增测试层** | `test_agent_flow.py`（26 收集项）<br>`test_api_contract.py`（12）<br>`test_splitter.py`（6）<br>`test_tools.py`（26）<br>`test_rag_model.py`（7）<br>`test_eval_smoke.py`（4，slow）<br>`e2e/test_browser_e2e.py`（8，e2e） | ✅ 收集 | 2026-11-16 建的 4 层测试体系 + 2026-11-17 新增工具层与检索层，详见 [`../docs/status/测试体系.md`](../docs/status/测试体系.md) |
| **H · 公共工具层** | `conftest.py` + `helpers.py` + `fake_backend.py` | ✅ | 假 LLM / 假检索 / 进程外假后端的 fixtures，本层自己不含用例 |

---

## 二、当前生效的 pytest 用例（112 个收集项）

### A 类 · 快回归（13 个，全部通过）

`pytest test/test_agent_timeout.py test/test_main_routes_covered.py -v`
→ **13 passed in 3.82s**

| 文件 | 用例 | 测什么 | 结果 |
|---|---|---|---|
| `test_agent_timeout.py` | `test_tool_status_success` | 工具返回非空 → `status=success` / `code=OK`，内容原样透传不包装 | ✅ |
| | `test_tool_status_empty` | 工具返回空串 → `status=empty` / `EMPTY_RESULT`（不是 success） | ✅ |
| | `test_tool_status_timeout` | 抛 `AgentTimeoutError` → `status=timeout` / `retryable=true`，且**必须回写 ToolMessage**，载荷是结构化 JSON | ✅ |
| | `test_tool_status_error` | 抛 `AgentToolError` → `status=error` / `retryable=false` | ✅ |
| | `test_timer_turns_slow_call_into_agent_timeout` | `Timer` 超时抛 `AgentTimeoutError` 而不是裸 `TimeoutError` | ✅ |
| | `test_timer_passes_through_normal_result` | 正常返回时 Timer 不改结果 | ✅ |
| | `test_is_expired_uses_deadline` | `deadline` 是绝对时间戳；过期 / 未过期 / 未设三种情况 | ✅ |
| | `test_synth_expired_returns_previous_answer` | 超时交出 `state["last_answer"]`，**不是**倒着找 AIMessage（会拿到 `"READY"` 占位） | ✅ |
| | `test_synth_expired_without_previous_answer` | 首次就超时 → 明确说超时，不留空 | ✅ |
| | `test_expired_state_routes_to_end` | `expired=True` 时 `should_continue` / `after_reflect` **都**返回 `"__end__"` | ✅ |
| | `test_agent_chat_endpoint_is_not_async` | AST 检查 `agent_chat` 不是 `async def` | ✅ |
| `test_main_routes_covered.py` | `test_every_router_is_imported_and_mounted` | `api/*.py` 每个 router 都必须被 `main.py` import **且** 挂载 | ✅ |
| | `test_no_orphan_router_import` | 反向检查：没有"import 了却不挂载"的孤儿 router | ✅ |

> ✅ 这 11 个用例**已进版本库**（2026-11-16 起）。

### B 类 · 慢用例（1 个，通过但极慢）

| 文件 | 测什么 | 结果 |
|---|---|---|
| `test_vector_split.py` | `vector_split()` 全流程：切分 → embed → 建带时间戳的集合 → 插入 → 建索引 → 加载 → **原子切 alias**；断言 alias 指向新集合且行数 > 0 | ✅ **passed，耗时 29 分 52 秒**（2026-11-16 复验）。已标 `@pytest.mark.slow`，默认快回归跳过 |

实测输出（2026-11-16）：`1667` 个片段 → alias `txt_data` → `txt_data_1794845929`，`query` 返回 10 行。

**为什么这么慢**：每次跑都要把 `txt/` 下全部文件重新切块并**全量重新 embed**
（1024 维，CPU 推理）。实测单批 32 块 ≈ 18 秒 → 光 embedding 就 ~16 分钟。
它不是"每次都该跑"的用例，是**改了摄取链路后跑一次**的验收用例。

> 📌 **2026-11-25 更新**：语料清理成 17 个文件 / 1517 块、嵌入换成 bge-m3 之后，
> 同一个用例**没有重跑**（要 15 分钟 + 花钱）。但同一条链路由
> `python -m utils.txt_spliter.vector_main` 实测 **14 分 20 秒**（14:50:54 → 15:05:14，
> exit 0，1517 块）。上面那些数字是**历史实测**，别当成当前语料的数字。

> ⚠️ **别把断言改成"查一次"** —— Milvus 的 `insert()` 是异步落盘的（返回只代表 WAL 收下，
> segment 还没 flush）。2026-11-16 第一次跑全量时这个用例就**失败**在这里：`query()` 返回 0 行，
> 而几分钟后同一个 query 返回 1667（数据没丢，是可见性窗口）。
> 所以断言走 `_wait_for_rows()` **轮询**（最多 180 秒），不要改成单次查询。

### C 类 · 新增 4 层测试体系（2026-11-16 落地，2026-11-17 清零 xfail + 加工具层与检索层）

`pytest -m "not slow and not e2e" -v`
→ **99 passed, 13 deselected, 0 xfailed**（2026-11-25 加了 `test_file_filter.py` 9 条）

> ⚠️ **耗时依赖 Milvus 在不在**（2026-11-25 在 99 条用例上实测）：
> **Milvus 不可达 → 108.70 秒**；**Milvus 在线 → 7.5–8.9 秒**（连续 6 次实测：
> 8.89 / 7.49 / 7.60 / 7.89 / 7.83 / 7.72 秒）。
> 慢的不是用例，是 `test_api_contract.py` 的 **12 个 setup** ——
> `main.py` 的 lifespan 每次启动都探一次 Milvus（`MilvusClient.list_collections()`），
> **Milvus 不通时这次探活阻塞约 10–11 秒**（实测），而 `TestClient` 每个用例都重新触发 lifespan。
> 看到"跑了一分多钟"先查 Milvus 是不是没起，不要以为用例变慢了。
>
> Milvus 在线时那 12 个 setup 每个只花 ~0.55 秒（`OllamaEmbeddings()` 构造 = httpx 客户端 +
> SSL 上下文，占 0.46 秒）→ 合计 ~6.7 秒；其余 87 条只要 1.43 秒。
>
> ⚠️ **这个数对机器负载敏感**：同一天在刚跑完索引重建 + Docker 镜像重建（机器满载）时测到
> **19.3–21.3 秒**，缓下来后回到 7.5–8.9 秒。**不是代码改动或嵌入模型切换造成的** ——
> 两个候选解释已实测排除：① Ollama 模型冷/热无差别（卸载 bge-m3 后 7.83 秒 vs 热跑 7.72 秒）；
> ② `import main` 不是元凶（`OllamaEmbeddings()` 构造：裸进程 0.46 秒、import 后 0.48 秒）。

| 文件 | 层 | 用例 | 测什么 | 结果 |
|---|---|---|---|---|
| `test_agent_flow.py` | L2 流程 | 17 独立 + 9 参数化 = **26 收集项** | 跑**真的 LangGraph 图**（假 LLM 剧本 + 假检索）：工具 4 态（success/empty/timeout/error）、**检索失败≠检索为空**（F4b）、tool_calls 按 id 不覆盖、检索素材真进 prompt、iter/reflect LLM 崩溃兜底、两个循环刹车（MAX_ITER / MAX_REFL）、三种超时时机、**超时兜底不交内部占位**、reflect 未知 action、`ask()` 恰好 5 个键；外加**公共不变式「悬空 tool_calls == 0」**参数化套 9 个场景 | ✅ **26 passed** |
| `test_api_contract.py` | L3 契约 | **12** | `TestClient` + `dependency_overrides`：三个接口都返 `response`（不含 `answer`）、缺字段 422、`/debug/simple`、`/available` 含 MiniMax、`/switch_model` 成功/失败（测完还原模型）、上传路径穿越 / 类型白名单 / 同名跳过或覆盖、**依赖单例**（P1-4） | ✅ **12 passed** |
| `test_splitter.py` | L2 切分 | **6** | 纯函数：空文本、单块、每块非空且 ≤300、**无内容丢失**、`max_chars` 真的生效、**默认参数来自 YAML** | ✅ **6 passed** |
| `test_tools.py` | L2 工具 | **26** | `calculator` 的 AST 白名单求值：算术 8 条 + 危险输入 10 条（`__import__` / `open` / `().__class__` / 字符串 / `True+1` / 变量名 / 大指数 / 长表达式 / 除零 / 语法错）+ 畸形输入 4 条参数化（**P1-2 的回归护栏**）；+ `rag_search` 异常归一化 4 条（**P2-7**） | ✅ **26 passed** |
| `test_rag_model.py` | L2 检索 | **7** | `core/rags/rags.py` 的失败语义：**检索失败抛 `RetrievalError`**（保留 `__cause__`）、**检索为空才返回 `[]`**、`/rag` 直连链路检索失败仍返回 200（**P2-7** 的回归护栏） | ✅ **7 passed** |
| `test_file_filter.py` | L2 入库去重 | **9** | `utils/docs/manager/filter.py` 的 MD5 内容哈希去重：首次必处理、同内容跳过、**不同文件名同内容也跳过**、**重传（源文件 mtime 变新）仍跳过**（旧实现死在这道 mtime 门上）、内容变了要重做、产物被删要重做、**索引只存文件名**（宿主机/容器共用）、**旧格式绝对路径索引仍能解析**、**回归网：同一文档传两次只产出一个文件、不冒 `_1` 副本** | ✅ **9 passed** |
| `test_eval_smoke.py` | L4 真环境 | **4**（标 `slow`） | 真 MiniMax + 真 Milvus：算式必调工具、问候有答案、知识库题走 `rag_search`、工具失败后不失控 | ✅ **4 passed**（实测 74.17 秒；S3/S4 天然 flaky） |

### D 类 · 浏览器 E2E（8 条，标 `e2e`）

`pytest -m e2e -v --tracing=retain-on-failure`
→ **8 passed in 66.93s**（2026-11-17）
跑法：**进程外假后端**（`test/fake_backend.py`）+ **专用 Streamlit（8511，注入 `API_BASE_URL`）**。
⚠️ 不复用用户已开的 Streamlit —— 复用来的进程没有 env 注入，拦截会失效。

⚠️ **Playwright 前置**：`playwright 1.58.0` 钉的是 **chromium build 1208**。
`python -m playwright install chromium` **只装 full chromium**，headless shell 要单独装：
```bash
python -m playwright install chromium-headless-shell
```
否则 pytest 会报 `Executable doesn't exist at ...chromium_headless_shell-1208`。
临时兜底：`--browser-channel=chromium`（用已装的 full chromium）。

| 编号 | 测什么 | 结果 |
|---|---|---|
| E1 | 智能问答：发问 → 用户消息 + 助手答案 | ✅ |
| E2 | 🗑 清空 → 消息归零 | ✅ |
| E3 | ⚙ 点击不报错（功能没写，只测不崩） | ✅ |
| E4 | 知识库问答 → 显示**假后端返回的答案**，且**不是**「(无答案)」 | ✅ **2026-11-17**（前端改读 `response`，P1-1 已修） |
| E5 | 仓库管理 → 传文件 → 出现统计**且数量 > 0** | ✅ |
| E6 | 三个页面互切 | ✅ |
| E7 | 后端返 500 → 页面显示"请求失败"而不是白屏 | ✅ |
| E8 | **真联调冒烟**（真后端 8000 + 真 MiniMax），真后端没起则 skip | ✅ **PASSED**（实测真后端在跑；109 秒里含这一次真 MiniMax 调用） |

---

## 三、非 pytest 内容

### `eval/` —— 离线工具路由评估（**非 pytest**，2026-11-22 从 `archive/` 迁出）

`test/` 下**唯一活着的离线评估**。跑 12 个 case，量 Agent"该不该调 `rag_search`"的
路由准确率 + 稳定性。

```bash
cd D:/PythonProject/ragmi
PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py            # 真 LLM
PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py --mock     # reflect 用假 LLM
```

两种模式都要真 MiniMax key，**都花钱**（`--mock` 只省 reflect 那一步）。

| 文件 | 内容 | 状态 |
|---|---|---|
| `eval/run_agent_eval.py` | 评估入口 | ✅ 活着（2026-11-18 修好四处失效） |
| `eval/data/agent_test_cases.json` | 12 个 case（query + 期望路由） | ⚠️ **口径是 v1 二值**（`expected_tool` 只有 chat/rag，没有 calculator/weather/web_search）→ 数字不可当基线，见 `docs/status/项目现状.md` §8 P0-1 |
| `eval/data/agent_eval_results.json` | 最新跑分快照 | ✅ **2026-11-18：路由准确率 75.0%（9/12）、稳定性 12/12、21 次工具调用全 `success`、中位耗时 25.79 秒** |

> ⚠️ **75.0% 低于 90% 的合格线**。2026-11-15 是 83.3%（10/12），差异**全部来自 T07 一次翻转**
> —— **LLM 路由本身有随机性**，两个数都只是单次采样，不是基线。

### `probes/` —— 手动探针（3 个，**已 gitignore，不上传仓**）

文件名不匹配 `python_files = test_*.py`，需从仓库根目录直接跑。

| 文件 | 测什么 | 结果 |
|---|---|---|
| `probes/probe_tool_status_overwrite.py` | 同一轮并发调同一个工具两次（一次成功一次超时），`tool_status` 会不会互相覆盖 | ✅ 2 个独立 key（`call_ok` / `call_timeout`），状态分别是 `{success, OK, false}` / `{timeout, TOOL_TIMEOUT, true}`，**无覆盖** |
| `probes/probe_minimax_dangling_400.py` | 直连 MiniMax，构造"有 `tool_calls` 没 tool 应答"的消息序列 | ✅ 悬空 → **HTTP 400** `invalid params, tool call and result not match (2013)`；对照组（有 ToolMessage）→ HTTP 200 |
| `probes/probe_dangling_tool_calls.py` | 真实图（真 MiniMax + 真 Milvus）跑一遍，每个 `tool_call` 是否都有对应 `ToolMessage` | ✅ **悬空 0 / 总调用 4**，`tool_status` 4 条，`iter_count=3`，`reflection_count=1`，答案正常渲染 |

> `probes/README.md` 里记的是"悬空 0 / 总调用 5"，当天复跑是 4 —— 次数随 LLM 决策浮动，
> **关键指标是"悬空 = 0"**，不是总数。

> ✅ 这 3 个探针发现的两个 bug **已转成 pytest 用例**（`test_agent_flow.py` 的 F1b +
> 公共不变式"悬空 tool_calls == 0"）。因此 `probes/` **2026-11-22 起不再进版本库** ——
> 只留本地做历史参照，干净 clone 看不到。

### `e2e/real_stack_check.py` —— 真栈全接口体检（**非 pytest**，2026-11-17 新增）

跟 `test_browser_e2e.py` 是两回事，**别混**：

| | `e2e/test_browser_e2e.py` | `e2e/real_stack_check.py` |
|---|---|---|
| 收录方式 | pytest 收集（标 `e2e`） | **故意不叫 `test_*.py`** → pytest 永不收集，手动跑 |
| 后端 | 进程外**假后端** | **真后端**（8000）+ 真 Milvus / Ollama / MiniMax |
| 确定性 | 确定性，可进 CI | 不确定（LLM 随机决策）+ **花钱** |
| 覆盖面 | 3 个页面的 UI 交互 | **9 个接口全打一遍**（含负路径）+ 3 个页面 |
| 浏览器 | headless | **开可见的 Chrome 窗口** |
| 产物 | trace / video | `test/e2e/_artifacts/`：5 张截图 + `report.html` |

跑法（仓库根目录，需真服务全在位）：

```bash
PYTHONIOENCODING=utf-8 python test/e2e/real_stack_check.py
# 可覆盖地址：E2E_API=http://127.0.0.1:8000  E2E_FRONTEND=http://localhost:8501
```

**实测结果（2026-11-17）：19 条全部通过，0 失败，耗时 74 秒**（A 组 14 + B 组 5）；
**2026-11-18 复测同样 19/19 通过，耗时 64 秒**。

- **A 组（14 条）· 接口**：从浏览器页面上下文里发 `fetch()` → **走真实浏览器网络栈，CORS 一并验了**。
  `/debug/simple`、`/available`、`/current_model`、`/switch_model`（失败分支 + 成功分支**并在 finally 里还原模型**）、
  `/agent/chat`（真 ReAct）、`/rag`（真检索）、`/chat`、`/agent/chat` 缺字段 → 422、
  `/api/upload-and-parse`、`/api/batch-upload-and-parse`（批量 2 个）、
  路径穿越 `../../evil.txt` → `failed_uploads`、`.exe` → `failed_uploads`、同名 → `skipped_files`。
- **B 组（5 条）· 页面**：智能问答真问答、🗑 清空归零、仓库管理上传、三个页面互切、
  知识库问答页 → **断言页面真的返回了答案**（P1-1 修好前这里是"命中已知缺陷"的宽松断言）。

**不污染仓库**：上传用 `e2e_probe_` 前缀的临时文件，测完从 `documents/` 和 `txt/` 删掉；
`txt/.file_filter.json` 先备份后还原。

**三个踩过的坑（脚本注释里都写了）**：

1. **切页要等标题变化，不能等输入框** —— `wait_for_selector(CHAT_INPUT)` 会命中**旧页面**还在 DOM 里的输入框，
   `fill()` 就打在即将被拆掉的元素上，消息永远发不出去（实测知识库问答页 180 秒超时）。
2. **等答案要等 spinner 消失 + 正文非空** —— 只等"消息数 ≥ 2"会假阳性（0.4 秒就放行，
   截出来助手区只有头像、正文是空的）。
3. **取正文要限定 `stChatMessageContent`** —— 直接取整条消息的 `innerText` 会把 Material 图标名
   （`smart_toy` / `face`）算进来，误判成"有内容"。

### `archive/` —— 过时测试脚本归档（**已 gitignore，不上传仓**）

不收集。逐文件实测状态、跑法和三个数据损坏坑见本地 `archive/README.md`。

> ⚠️ **2026-11-22 起这个目录不再进版本库**。里面一半能跑一半不能（LangSmith 那几个直接 401 /
> ImportError），留在仓里只会让人误以为是现行测试。**干净 clone 看不到这个目录**，
> 需要历史脚本时看本地工作区或 `git log -- test/archive/`。

| 文件 | 测什么 | 实测结果（2026-11-15） |
|---|---|---|
| ~~`archive/scripts/run_agent_eval.py`~~ | — | ✅ **已迁到 `eval/run_agent_eval.py`**，2026-11-18 修好四处失效 |
| `archive/scripts/run_v1_baseline.py` | 走 HTTP 打 `/agent/chat`，拿 v1 baseline | ⚠️ **能跑，但后端没起时会把 `data/v1_baseline_results.json` 覆写成 0/12 = 0.0%**（实测踩过） |
| `archive/scripts/retry_failed_cases.py` | 重跑上轮失败 case | ⚠️ **能跑，但只是读缓存的 `data/v1_baseline_results.json` 重算并重印**，不是新测量 |
| `archive/scripts/langsmith_setup.py` | 把 12 个 case 传成 LangSmith Dataset | ❌ **401 Unauthorized** `Invalid token` |
| `archive/scripts/langsmith_evaluators.py` | 两个 evaluator 纯函数 | ✅ import OK，`tool_choice_evaluator` / `answer_keyword_evaluator` 都在 |
| `archive/scripts/langsmith_eval.py` | 用 LangSmith 跑 evaluate | ❌ `ModuleNotFoundError: No module named 'test.langsmith_evaluators'` |
| `archive/scripts/evil_proxy.py` | 假代理：拦 `/api/tokenize` 返 502，其它透传 | ✅ 正常（实测：透传 200 / 拦截 502）。**与 Agent 无关** |
| `archive/scripts/repro_embed_clients.py` | 对比直连 Ollama HTTP vs `langchain_ollama` 的 4 条路径 | ✅ **当前环境 4/4 全过**（无代理干扰）。**与 Agent 无关** |
| ~~`archive/data/agent_test_cases.json`~~ | — | ✅ **已迁到 `eval/data/`** |
| ~~`archive/data/agent_eval_results.json`~~ | — | ✅ **已迁到 `eval/data/`**（内容也更新为 2026-11-18 的 75.0% 快照） |
| `archive/data/v1_baseline_results.json` | v1 baseline（75%，9/12，平均 48.28s） | ✅ 只留本地 |

### `fixtures/` —— 手工测试素材

| 文件 | 状态 |
|---|---|
| `fixtures/sample.txt` | ✅ **已进版本库** —— 被 `docs/plan/repair-closeout-{design,impl}.md` 的 curl 上传命令引用，干净 clone 上要能直接跑 |
| ~~`fixtures/fake.exe`~~ | ❌ **已删除**（2026-11-16）—— 8 字节占位文件，全仓无引用 |

---

## 四、这些测试**没有**覆盖什么

别把上面的绿色当成质量保证：

1. **reflect prompt 的"工具失败时不判 `re_iterate`"硬约束** —— 假 reflect 被剧本编排，
   **原理上测不到**；只有 S4（真 LLM）能碰到，且天然 flaky。这是本轮**明确不覆盖**的部分。
2. **评估集口径过时** —— 二值 `expected_tool` vs v2.2 的 4 个工具（见上）。
3. **真实检索链路没被 *pytest* 自动验证** —— L2 层用的是**假检索**，`core/rags/rags.py` 的真实
   `retrieve()`（Milvus + Ollama embedding）只有 `test_vector_split.py` 那一条 25 分钟的慢用例碰到。
   （`e2e/real_stack_check.py` 会真的走一遍检索 —— 但它不是 pytest 用例，跑它要花钱且要真服务全在位。）
4. **`retryable` 还不能细分** —— ✅ "检索失败 ≠ 检索为空"已经修好（P2-7，2026-11-17：
   `core/rags/rags.py` 现在抛 `RetrievalError`，`[]` 只表示真的没查到）。
   但工具层只拿到 `AgentToolError` 这一个"其他错误"的桶，
   区分不出限流/服务不可用（可重试）与参数错/代码 bug（不可重试）。
5. **多轮记忆没测** —— `session_id` → `thread_id` 传了但图没有 checkpointer，
   多轮持久化**未实现**，没有可测的东西。
6. **代码覆盖率不是全量**（实测 2026-11-22，`--cov=.`）：`agent/` **91%**、全项目 **56%**。
   低覆盖集中在摄取（`utils/docs/` 11~20%）和 Streamlit 页面（`web_page/` 0%，
   只被浏览器 E2E 点到、不在 pytest 覆盖范围内）。

---

## 五、接下来

新测试体系（4 层，80 独立用例 / 89 收集项）的设计与实施计划：

- 设计：[`../docs/status/测试体系.md`](../docs/status/测试体系.md)
- 实施计划：[`../docs/plan/2026-11-16-test-suite-impl.md`](../docs/plan/2026-11-16-test-suite-impl.md)

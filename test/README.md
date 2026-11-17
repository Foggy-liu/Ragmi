# test/ 目录说明

> **实测日期：2026-11-15 / 目录整理 + 4 层测试体系落地：2026-11-16 / 债务清零 + 新增工具层：2026-11-17**。
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
├── test_eval_smoke.py          # L4 真环境冒烟（4 用例）            ← 生效，标 slow
├── conftest.py                 # 假 LLM / 假检索 / 假后端 fixtures
├── helpers.py                  # 公共工具层（假 LLM 剧本、消息工具）
├── fake_backend.py             # 进程外假后端（浏览器层用）
├── e2e/                        # L4 浏览器层
│   ├── test_browser_e2e.py     #   E1–E8（标 e2e，假后端）
│   ├── real_stack_check.py     #   真栈全接口体检（**非 pytest**，见下）
│   └── _artifacts/             #   真栈产物（截图 + HTML 报告，已 gitignore）
├── probes/                     # 手动探针脚本（非 pytest）
├── archive/                    # 过时测试脚本的只读归档（不收集）
│   ├── scripts/                #   8 个 v1/v2.1 脚手架
│   └── data/                   #   3 个历史跑分快照
└── fixtures/                   # 手工测试素材（sample.txt 已进版本库）
```

**收集规则**（`pytest.ini`）：

```ini
testpaths = test
python_files = test_*.py
norecursedirs = archive probes .* build dist node_modules venv __pycache__
```

→ `test/probes/` 与 `test/archive/` **永不收集**。

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

## 二、当前生效的 pytest 用例（103 个收集项）

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

> ⚠️ **`test/test_agent_timeout.py` 还没进 git**（2026-11-15 新建，一直是 untracked）。
> 这 11 个用例是当前唯一的核心回归网 —— 提交新测试体系时**务必一并 `git add`**。

### B 类 · 慢用例（1 个，通过但极慢）

| 文件 | 测什么 | 结果 |
|---|---|---|
| `test_vector_split.py` | `vector_split()` 全流程：切分 → embed → 建带时间戳的集合 → 插入 → 建索引 → 加载 → **原子切 alias**；断言 alias 指向新集合且行数 > 0 | ✅ **passed，耗时 29 分 52 秒**（2026-11-16 复验）。已标 `@pytest.mark.slow`，默认快回归跳过 |

实测输出：`1667` 个片段 → alias `txt_data` → `txt_data_1794845929`，`query` 返回 10 行。

**为什么这么慢**：每次跑都要把 `txt/` 下 22 个文件（1.1 MB）重新切成 1667 块并**全量重新 embed**
（bge-large，1024 维，CPU 推理）。实测单批 32 块 ≈ 18 秒 → 光 embedding 就 ~16 分钟。
它不是"每次都该跑"的用例，是**改了摄取链路后跑一次**的验收用例。

> ⚠️ **别把断言改成"查一次"** —— Milvus 的 `insert()` 是异步落盘的（返回只代表 WAL 收下，
> segment 还没 flush）。2026-11-16 第一次跑全量时这个用例就**失败**在这里：`query()` 返回 0 行，
> 而几分钟后同一个 query 返回 1667（数据没丢，是可见性窗口）。
> 所以断言走 `_wait_for_rows()` **轮询**（最多 180 秒），不要改成单次查询。

### C 类 · 新增 4 层测试体系（2026-11-16 落地，2026-11-17 清零 xfail + 加工具层与检索层）

`pytest -m "not slow and not e2e" -v`
→ **90 passed, 13 deselected in 15.39s**（**0 xfailed**）

| 文件 | 层 | 用例 | 测什么 | 结果 |
|---|---|---|---|---|
| `test_agent_flow.py` | L2 流程 | 17 独立 + 9 参数化 = **26 收集项** | 跑**真的 LangGraph 图**（假 LLM 剧本 + 假检索）：工具 4 态（success/empty/timeout/error）、**检索失败≠检索为空**（F4b）、tool_calls 按 id 不覆盖、检索素材真进 prompt、iter/reflect LLM 崩溃兜底、两个循环刹车（MAX_ITER / MAX_REFL）、三种超时时机、**超时兜底不交内部占位**、reflect 未知 action、`ask()` 恰好 5 个键；外加**公共不变式「悬空 tool_calls == 0」**参数化套 9 个场景 | ✅ **26 passed** |
| `test_api_contract.py` | L3 契约 | **12** | `TestClient` + `dependency_overrides`：三个接口都返 `response`（不含 `answer`）、缺字段 422、`/debug/simple`、`/available` 含 MiniMax、`/switch_model` 成功/失败（测完还原模型）、上传路径穿越 / 类型白名单 / 同名跳过或覆盖、**依赖单例**（P1-4） | ✅ **12 passed** |
| `test_splitter.py` | L2 切分 | **6** | 纯函数：空文本、单块、每块非空且 ≤300、**无内容丢失**、`max_chars` 真的生效、**默认参数来自 YAML** | ✅ **6 passed** |
| `test_tools.py` | L2 工具 | **26** | `calculator` 的 AST 白名单求值：算术 8 条 + 危险输入 10 条（`__import__` / `open` / `().__class__` / 字符串 / `True+1` / 变量名 / 大指数 / 长表达式 / 除零 / 语法错）+ 畸形输入 4 条参数化（**P1-2 的回归护栏**）；+ `rag_search` 异常归一化 4 条（**P2-7**） | ✅ **26 passed** |
| `test_rag_model.py` | L2 检索 | **7** | `core/rags/rags.py` 的失败语义：**检索失败抛 `RetrievalError`**（保留 `__cause__`）、**检索为空才返回 `[]`**、`/rag` 直连链路检索失败仍返回 200（**P2-7** 的回归护栏） | ✅ **7 passed** |
| `test_eval_smoke.py` | L4 真环境 | **4**（标 `slow`） | 真 MiniMax + 真 Milvus：算式必调工具、问候有答案、知识库题走 `rag_search`、工具失败后不失控 | ✅ **4 passed**（实测 162 秒；S3/S4 天然 flaky） |

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

### `probes/` —— 手动探针（3 个，全部通过）

文件名不匹配 `python_files = test_*.py`，需从仓库根目录直接跑。

| 文件 | 测什么 | 结果 |
|---|---|---|
| `probes/probe_tool_status_overwrite.py` | 同一轮并发调同一个工具两次（一次成功一次超时），`tool_status` 会不会互相覆盖 | ✅ 2 个独立 key（`call_ok` / `call_timeout`），状态分别是 `{success, OK, false}` / `{timeout, TOOL_TIMEOUT, true}`，**无覆盖** |
| `probes/probe_minimax_dangling_400.py` | 直连 MiniMax，构造"有 `tool_calls` 没 tool 应答"的消息序列 | ✅ 悬空 → **HTTP 400** `invalid params, tool call and result not match (2013)`；对照组（有 ToolMessage）→ HTTP 200 |
| `probes/probe_dangling_tool_calls.py` | 真实图（真 MiniMax + 真 Milvus）跑一遍，每个 `tool_call` 是否都有对应 `ToolMessage` | ✅ **悬空 0 / 总调用 4**，`tool_status` 4 条，`iter_count=3`，`reflection_count=1`，答案正常渲染 |

> `probes/README.md` 里记的是"悬空 0 / 总调用 5"，当天复跑是 4 —— 次数随 LLM 决策浮动，
> **关键指标是"悬空 = 0"**，不是总数。

> **待办**：这 3 个探针发现的两个 bug 修完**没有变成 pytest 用例**。新测试体系落地后，
> 探针改写成 pytest（`test_agent_flow.py` 的 F1b + 公共不变式），
> 然后把 `probes/` 整个并入 `test/archive/`。

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

**实测结果（2026-11-17）：19 条全部通过，0 失败，耗时 74 秒**（A 组 14 + B 组 5）。

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

### `archive/` —— 过时测试脚本归档（11 个文件）

不收集。逐文件实测状态、跑法和三个数据损坏坑见 [`archive/README.md`](./archive/README.md)。

| 文件 | 测什么 | 实测结果 |
|---|---|---|
| `archive/scripts/run_agent_eval.py` | 跑 12 个 case 出工具路由准确率 | ⚠️ **默认（真实 LLM）模式能跑通 12/12 case**（需 `PYTHONPATH` 指向仓库根）；`--mock` 模式 ImportError |
| `archive/scripts/run_v1_baseline.py` | 走 HTTP 打 `/agent/chat`，拿 v1 baseline | ⚠️ **能跑，但后端没起时会把 `data/v1_baseline_results.json` 覆写成 0/12 = 0.0%**（实测踩过，已 `git checkout` 还原） |
| `archive/scripts/retry_failed_cases.py` | 重跑上轮失败 case | ⚠️ **能跑，但只是读缓存的 `data/v1_baseline_results.json` 重算并重印**，不是新测量 |
| `archive/scripts/langsmith_setup.py` | 把 12 个 case 传成 LangSmith Dataset | ❌ **401 Unauthorized** `Invalid token` |
| `archive/scripts/langsmith_evaluators.py` | 两个 evaluator 纯函数 | ✅ import OK，`tool_choice_evaluator` / `answer_keyword_evaluator` 都在 |
| `archive/scripts/langsmith_eval.py` | 用 LangSmith 跑 evaluate | ❌ `ModuleNotFoundError: No module named 'test.langsmith_evaluators'` |
| `archive/scripts/evil_proxy.py` | 假代理：拦 `/api/tokenize` 返 502，其它透传 | ✅ 正常（实测：透传 200 / 拦截 502）。**与 Agent 无关** |
| `archive/scripts/repro_embed_clients.py` | 对比直连 Ollama HTTP vs `langchain_ollama` 的 4 条路径 | ✅ **当前环境 4/4 全过**（无代理干扰）。**与 Agent 无关** |
| `archive/data/agent_test_cases.json` | 12 个 case（v1 时代设计，`expected_tool` 只有 chat/rag 二值，**没有 calculator / weather / web_search**，所以口径已过时） | ✅ 数据完整 |
| `archive/data/agent_eval_results.json` | v2.1 时代快照（92%），保持原样 | ✅ |
| `archive/data/v1_baseline_results.json` | v1 baseline（75%，9/12，平均 48.28s），保持原样 | ✅ |

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
4. **`empty` 与"检索失败"仍分不开** —— 工具层现在**能**测到 `empty` 状态（假检索返回空串），
   但根因还在：`core/rags/rags.py` 的 `retrieve()` 用 `except Exception: return []`
   把异常吞了，工具侧区分不了"检索为空"和"检索失败"。这是 `retryable` 精细化的前置。
5. **多轮记忆没测** —— `session_id` → `thread_id` 传了但图没有 checkpointer，
   多轮持久化**未实现**，没有可测的东西。

---

## 五、接下来

新测试体系（4 层，80 独立用例 / 89 收集项）的设计与实施计划：

- 设计：[`../docs/status/测试体系.md`](../docs/status/测试体系.md)
- 实施计划：[`../docs/plan/2026-11-16-test-suite-impl.md`](../docs/plan/2026-11-16-test-suite-impl.md)

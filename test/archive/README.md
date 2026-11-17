# test/archive/ —— 过时测试脚本的只读归档

> **一句话**：这个目录**只存放过时的测试脚本和历史跑分快照**，不属于当前测试流程。
> `pytest.ini` 设了 `norecursedirs = archive probes`，**永不收集**。

**这里没有任何东西是"现在的测试"。** 当你看当前测试体系时，看
[`../README.md`](../README.md)；当你需要知道"以前怎么搭的"或"历史分数是多少"时，才来这里。

## 目录结构

| 路径 | 内容 |
|---|---|
| `scripts/` | 8 个 v1 / v2.1 时代的测试脚手架（`.py`） |
| `data/` | 3 个历史跑分快照（`.json`） |

## 为什么直接归档而不删

`agent` 的图结构、节点函数名、state 字段在 v1 → v2 → v2.1 → v2.2 四轮里改过好几次。
这些脚本是那几次演进的**时间切片** —— 记着当时评了哪些 case、期望工具路由是什么、
LangSmith dataset 怎么搭的。作为参考资料它们很有价值；作为可执行代码，一半能跑一半不能。

2026-11-12 首次归档到 `test/befor/`（当时叫这名字是笔误）；**2026-11-16 改名为 `archive/`
并拆成 `scripts/` + `data/`**。`api_dashboard.{html,jpeg}`（653 KB API 面板素材）已在
2026-11-16 删除 —— 全仓无任何文档引用它们。

## `scripts/` 逐文件实测状态（2026-11-15 实跑）

| 文件 | 作用 | 实测结果 |
|---|---|---|
| `run_agent_eval.py` | 离线评估入口，跑 `data/agent_test_cases.json` 的 12 个 case 出准确率 | ⚠️ **真实 LLM 模式能跑通**（12/12 case，0 异常）；只有 `--mock` 分支 ImportError（`agent.nodes.reflect` 已改名 `reflect_node`）。另外它读 `debug_result["iterations"]`，v2.2 是 `iter_count` → 该字段恒为 0 |
| `run_v1_baseline.py` | 走 HTTP 打 `/agent/chat` 拿 baseline | ⚠️ 脚本本身不依赖 v1 代码，能跑；但**后端没起时会把 `data/v1_baseline_results.json` 覆写成 0/12 = 0.0%**（实测踩过，靠 `git checkout` 还原） |
| `retry_failed_cases.py` | 重跑上轮失败的 case | ⚠️ **能跑，但它只是读缓存的 `data/v1_baseline_results.json` 找 `tool_chosen == "ERROR"` 的 case 再重算** —— 不是新测量，只是把缓存数字重印一遍 |
| `langsmith_setup.py` | 把 12 个 case 传成 LangSmith Dataset | ❌ **401 Unauthorized** `Invalid token`（不是"没意义"，是根本连不上） |
| `langsmith_evaluators.py` | 两个 evaluator：`tool_choice_evaluator` + `answer_keyword_evaluator` | ✅ import OK，纯函数逻辑仍成立 |
| `langsmith_eval.py` | 用 LangSmith 跑 evaluate 实验 | ❌ `ModuleNotFoundError: No module named 'test.langsmith_evaluators'`（import 路径对不上；目录改名后更对不上了） |
| `evil_proxy.py` | 假代理：拦 `/api/tokenize` 返 502，其它透传 | ✅ 正常（实测：透传 200 / 拦截 502）。**与 Agent 无关** —— 是查 Ollama embedding 客户端不一致的调试脚本 |
| `repro_embed_clients.py` | 对比直连 Ollama HTTP vs `langchain_ollama` 的 4 条路径 | ✅ **当前环境 4/4 全过**（无代理干扰）。**与 Agent 无关** —— 同上 |

> 最后两个是 **Ollama embedding 的调试脚本**，不是 Agent 的测试。留在归档里是因为
> "索引端与检索端用了两个不同 embedding 客户端"这个问题还没正式修（见
> `docs/status/项目现状.md`），将来还得回来查。

## `data/` 逐文件

| 文件 | 内容 |
|---|---|
| `agent_test_cases.json` | 12 个评估 case（T01–T12），带 `expected_tool` / `answer_keywords`。⚠️ `expected_tool` 只有 chat/rag **二值**，没跟上 v2.2 的 4 个工具（`rag_search` / `calculator` / `weather` / `web_search`）→ 口径已过时 |
| `agent_eval_results.json` | v2.1 时代跑分快照（92%）。**历史快照，保持原样** |
| `v1_baseline_results.json` | v1 baseline 结果（75%，9/12，平均 48.28s）。**历史快照，保持原样** |

## 跑归档脚本的正确姿势

**必须显式设 `PYTHONPATH` 指向仓库根**。这几个脚本用 `Path(__file__).parent.parent` 找包根，
文件从 `test/` 挪到 `test/archive/scripts/` 之后，那个路径变成了 `test/archive/`，
`import agent` 直接失败：

```bash
cd test/archive/scripts
PYTHONIOENCODING=utf-8 PYTHONPATH="D:/PythonProject/ragmi" python run_agent_eval.py
```

（Windows 上还要 `PYTHONIOENCODING=utf-8`，否则脚本里打印 `✓`/`✗` 会 GBK 编码报错。）

### 三个坑

1. **`run_v1_baseline.py` 会毁数据** —— 后端没起时它把 12 个 case 全记成 ERROR，
   然后把 `data/v1_baseline_results.json` 覆写成 `accuracy: 0.0`。跑之前先 `git stash`/`git checkout` 兜底。
2. **`run_agent_eval.py` 会覆写 `data/agent_eval_results.json`** —— 跑完 12 个 case 才写文件，
   中途 Ctrl+C 不会写；但跑完了就会盖掉 v2.1 的历史快照，想保留就先备份。
3. **`retry_failed_cases.py` 的数字是假的** —— 它输出的 "Accuracy: 9/12 = 75.0%" 来自缓存文件，
   不是本次测量。

## 当前生效的测试在哪

上一级 `test/`：

- `test_agent_timeout.py` —— 11 个用例（超时 / 异常 / 工具状态 / 端点同步性），不连外部服务
- `test_main_routes_covered.py` —— AST 扫描 `api/*.py`，防止出现"写了路由模块但没挂载"的死代码
- `test_vector_split.py` —— `vector_split()` 端到端（需 Milvus + Ollama，**实测 25 分 29 秒**），
  已标 `@pytest.mark.slow`

完整的分类与逐文件实测结果见上一级 [`../README.md`](../README.md)。

> ⚠️ **待补的债**：v2.2 的完整测试流程还没搭 —— `probe_*.py` 里发现的两个 bug
> （`tool_status` 覆盖、`tool_calls` 悬空）修完之后**没有变成 pytest 用例**。
> 新测试体系的设计见 [`../../../docs/status/测试体系.md`](../../../docs/status/测试体系.md)。

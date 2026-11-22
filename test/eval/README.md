# test/eval/ —— 离线工具路由评估

> **一句话**：这是 `test/` 下**唯一活着的离线评估**。跑 12 个 case，量 Agent
> "该不该调 `rag_search`" 的路由准确率 + 稳定性。
>
> `test/` 其余目录全是 pytest 用例；**这个目录不是 pytest 用例**
> （文件名不匹配 `test_*.py`，pytest 永不收集）。

## 为什么它不在 `test/archive/` 里

`test/archive/` 里的东西是 **v1 / v2.1 时代的死脚本**，只留本地做历史参照、不上传仓
（见仓库根 `.gitignore`）。而这个评估脚本 **2026-11-18 修好了四处失效**，是当前
唯一能产出"工具路由准确率"这个数字的入口 —— 放进 archive 会名不副实。

## 跑法

```bash
# 真实 LLM 模式（agent + reflect 都用真 MiniMax，12 个 case）
cd D:/PythonProject/ragmi
PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py

# --mock 模式：只把 reflect 的 LLM 换成 MockLLM，agent 仍是真实 LLM
#              （省反思那一步的钱，路由准确率仍报）
PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py --mock
```

> ⚠️ **两种模式都要真实 MiniMax key，都要花钱**。`--mock` 只省 reflect 的调用。
>
> ⚠️ **跑之前先想清楚要哪种**：`--mock` 反映的**不是**真实反思能力，
> 只用来验证"图走不走得通、路由对不对"。看真实数字用**不带 `--mock`** 的那一条。

## 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `run_agent_eval.py` | 评估入口 | ✅ 活着的 |
| `data/agent_test_cases.json` | 12 个 case（query + 期望路由） | ⚠️ **口径是 v1 二值设计**（`expected_tool` 只有 `chat`/`rag`，没有 calculator/weather/web_search）→ 数字不可当基线用，见 `docs/status/项目现状.md` §8 P0-1 |
| `data/agent_eval_results.json` | **真实 LLM 跑分快照**（2026-11-18：路由准确率 **75.0%** = 9/12，稳定性 100%，21 次工具调用全 success） | ✅ 当前有效 |
| `data/agent_eval_results_mock.json` | `--mock` 模式的输出（**单独一个文件**） | 🚫 不进仓（`.gitignore`） |

> ⚠️ **两种模式写不同的文件**（2026-11-22 定的规矩）：
> 之前 `--mock` 和真实模式**都写同一个 `agent_eval_results.json`** ——
> 实测踩过一次，跑完 `--mock` 把 75.0% 的真实基线冲成了 91.67%，
> 而真实快照**从没被提交过**（只在工作区），差点丢。
> 现在 `--mock` 写 `agent_eval_results_mock.json`，**碰不到真实快照**。

## 数字怎么读

| 字段 | 含义 | 合格线 |
|---|---|---|
| `routing_accuracy` | 期望路由与实际路由匹配率 | ≥ 90%（**当前 75.0%，未达标**） |
| `stability` | 不抛异常的 case 占比 | 100%（当前 100%） |
| `exceptions` | 抛异常的 case 数 | 0（当前 0） |
| `tool_status_distribution` | 工具调用四态分布 | — |
| `reflect_final_action` | reflect 最终决策分布 | 全部 `end` |

> ⚠️ **单次采样，不是基线**。2026-11-15 是 83.3%（10/12），2026-11-18 是 75.0%（9/12），
> 差异全部来自 T07 一次翻转（"Python 的 list 和 tuple 有什么区别"该不该检索）。
> **LLM 路由本身有随机性** —— 两个数都只是采样点。要真基线得重建评估集 + 接 CI。

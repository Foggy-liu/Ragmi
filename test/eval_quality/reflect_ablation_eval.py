"""test/eval_quality/reflect_ablation_eval.py —— 线 B：反思消融评测。

测什么
------
反思节点（`agent/nodes/reflect_node.py`）**判别力**：给它一份候选答案 + 一份工具素材，
它该不该要求重写（`rewrite`）？判对了没有？

为什么要单独一条线
------------------
线 A 测的是"答案好不好"（端到端跑图）。线 B 测的是"反思这一步准不准"——
它是线 A 的**机制层**，同样能讲清楚原理，但不需要跑检索、不需要 Milvus。

零改代码
--------
`reflect_node(state, llm=…)` 的 LLM 可注入 → 直接调生产函数，
**测的就是生产 prompt 原样**（`agent/prompts/reflect_prompt.py`），`agent/` 一个字不改。
LLM 用 `reflect_node._get_llm()` 私有构造器而不是自己抄一遍 ——
抄一遍会在生产改了以后**静默漂移**，导入则不可能漂移。

state 布局（语料 §2.2，三条读取点共同决定）
------------------------------------------
`Human → Tool → AI`：
- `reflect_node.py:97` 取 `messages[0]` 当问题 → HumanMessage 必须在 index 0
- `reflect_node.py:98` 倒着找最后一条 AIMessage 当答案 → AI 放最后
- `material.py:15-33` 取"最后一条 HumanMessage 之后的全部 ToolMessage" → Tool 在 Human 之后

四个指标（设计稿 §7.3）
----------------------
| 指标 | 分母 | 分子 |
|---|---|---|
| **真阳性率** | 期望 `rewrite` 的格子 | 判了 `rewrite` |
| **假阳性率** | 好答案格子（期望 `end`） | 判了 `rewrite`（误报 → 反思不停 → 烧 token） |
| **不可判定率** | 期望 `end` 且不可判定的格子 | 判了 `end`（素材沉默 → 无从质疑，正确行为） |

⚠️ **不可判定单独报，不与真阳性混算** —— ④类坏答案（编造）的 `end` 是**正确行为**，
算进"漏判"会低估反思节点。

`re_iterate` 是**异常桶**：语料 §7 规定线 B 恒为 `tool_status=success`，
不触发 prompt 的硬约束，出现即为异常 → 单独报告，不并进四个指标。

改后改善率（`--improve`）
-------------------------
"这个才是反思有用的证据"（设计稿 §7.3）：判了 `rewrite` → synth 重写 →
用线 A 同一把尺子（`judge_answer_quality.py` + B 组 `must_contain`）给重写后的答案打分，
比原来高多少。**第二轮单独跑，不混进本轮四个指标。**

复算信息
--------
- 执行体 LLM：MiniMax-M3.1-Flash（与生产一致）
- 被测 prompt：`agent/prompts/reflect_prompt.py`（生产原样）
- 判分（仅 `--improve`）：MiniMax-M2.5（同线 A）
- 快照：见 `results/reflect_ablation_<date>.json`，**永不覆盖**
"""

import argparse
import json
import sys
from pathlib import Path

# 仓库根 = eval_quality/ → test/ → <repo>
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# ⚠️ 不能写 `from agent.nodes import reflect_node` ——
# `agent/nodes/__init__.py:11` 把**函数** reflect_node 导出到了包属性上，
# 同名遮蔽了子模块 → `from agent.nodes import reflect_node` 拿到的是函数不是模块。
# 用 import_module 从 sys.modules 里取真正的模块对象。
from importlib import import_module

reflect_node_mod = import_module("agent.nodes.reflect_node")

CASE_FILE = Path(__file__).resolve().parent / "data" / "reflect_ablation_cases.json"
AQ_CASE_FILE = Path(__file__).resolve().parent / "data" / "answer_quality_cases.json"

EXECUTOR_MODEL = "MiniMax-M3.1-Flash"
JUDGE_MODEL = "MiniMax-M2.5"

TOOL_CALL_ID = "call_test_1"


# --------------------------------------------------------------------------
# 造 state / 调 LLM
# --------------------------------------------------------------------------
class RecordingLLM:
    """包一层把 reflect 的原始判定留底。

    `reflect_node` 只把 `next_action` / `critique` 返回给图，
    `is_sufficient` 和原始解析结果会被丢掉 —— 这里留底，报告才能区分
    "reflect 真的判 insuffcient" 和 "解析失败触发的兜底 rewrite"。

    解析失败时 reflect_node 会兜底成 `rewrite`（`reflect_node.py:119-122`），
    那是**故障**不是判定 —— 靠 `error` 标记把它从分母里剔出去。
    """

    def __init__(self, inner):
        self.inner = inner
        self.last = None
        self.error = None

    def invoke(self, *a, **kw):
        try:
            out = self.inner.invoke(*a, **kw)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.last = None
            raise
        self.last = out
        return out


def build_state(question, material, answer):
    """按语料 §2.2 造 state：Human → Tool → AI。

    `tool_status` 恒为 `success` —— 素材"不给"不等于"检索为空"，
    改成 `empty` 会触发 prompt 的硬约束，把诚实性维度污染掉（语料 §2.3）。
    """
    return {
        "messages": [
            HumanMessage(content=question),
            ToolMessage(content=material, name="rag_search", tool_call_id=TOOL_CALL_ID),
            AIMessage(content=answer),
        ],
        "tool_status": {
            TOOL_CALL_ID: {
                "tool": "rag_search",
                "status": "success",
                "code": "OK",
                "retryable": False,
            }
        },
        "last_critique": "",
        "reflection_count": 0,
        "iter_count": 0,
    }


def _get_executor_llm():
    """生产反射节点的 LLM 构造器（`reflect_node._get_llm`）。

    ⚠️ 直接导入私有函数而不是抄一遍 —— 抄一遍会在生产改了以后静默漂移。
    """
    return reflect_node_mod._get_llm()


# --------------------------------------------------------------------------
# 跑一轮
# --------------------------------------------------------------------------
def run_case(case, question, llm, executor_model):
    """跑一个用例，返回一行结果。"""
    state = build_state(question, case["material"], case["answer"])
    rec = RecordingLLM(llm)
    try:
        out = reflect_node_mod.reflect_node(state, llm=rec)
    except Exception as e:
        return {
            "id": case["id"],
            "question_id": case["question_id"],
            "material_kind": case["material_kind"],
            "answer_kind": case["answer_kind"],
            "expect_action": case["expect_action"],
            "expect_class": case["expect_class"],
            "action": None,
            "critique": "",
            "is_sufficient": None,
            "error": f"{type(e).__name__}: {e}",
            "executor_model": executor_model,
        }

    parsed = rec.last
    return {
        "id": case["id"],
        "question_id": case["question_id"],
        "material_kind": case["material_kind"],
        "answer_kind": case["answer_kind"],
        "expect_action": case["expect_action"],
        "expect_class": case["expect_class"],
        "action": out.get("next_action"),
        "critique": (out.get("last_critique") or "")[:400],
        "is_sufficient": getattr(parsed, "is_sufficient", None),
        # 解析失败触发的兜底 rewrite —— 记下来，不进分母
        "error": rec.error,
        "executor_model": executor_model,
    }


# --------------------------------------------------------------------------
# 指标（设计稿 §7.3）
# --------------------------------------------------------------------------
def classify(row):
    """把一次判定落到四个桶里。"""
    if row.get("error"):
        return "error"
    action = row.get("action")
    expect_class = row["expect_class"]
    if action == "re_iterate":
        # 语料 §7：线 B 恒为 success，出现 re_iterate 即异常，单独报告
        return "anomaly_re_iterate"
    if expect_class == "true_positive":
        return "tp_hit" if action == "rewrite" else "tp_miss"
    if expect_class == "true_negative":
        # 好答案被改写 = 误报
        return "tn_fp" if action == "rewrite" else "tn_ok"
    if expect_class == "undetermined":
        # 不可判定：判 end 是正确行为，判 rewrite 才是"越界质疑"
        return "ud_ok" if action == "end" else "ud_over"
    return "unknown"


def summarize(rows):
    """算四个指标 + 异常桶。分母里剔掉 error（故障不是判定）。"""
    buckets = {}
    for r in rows:
        r["bucket"] = classify(r)
        buckets[r["bucket"]] = buckets.get(r["bucket"], 0) + 1

    tp_total = buckets.get("tp_hit", 0) + buckets.get("tp_miss", 0)
    tn_total = buckets.get("tn_fp", 0) + buckets.get("tn_ok", 0)
    ud_total = buckets.get("ud_ok", 0) + buckets.get("ud_over", 0)

    return {
        "counts": buckets,
        "true_positive_total": tp_total,
        "true_positive_rate": (buckets.get("tp_hit", 0) / tp_total) if tp_total else None,
        "false_positive_total": tn_total,
        "false_positive_rate": (buckets.get("tn_fp", 0) / tn_total) if tn_total else None,
        "undetermined_total": ud_total,
        "undetermined_rate": (buckets.get("ud_ok", 0) / ud_total) if ud_total else None,
        "anomaly_re_iterate": buckets.get("anomaly_re_iterate", 0),
        "errors": buckets.get("error", 0),
        "judged": sum(v for k, v in buckets.items() if k != "error"),
    }


def summarize_by_axis(rows):
    """按素材种类把 48 格拆成**两条轴**（【实测 2026-11-27 发现的语义分叉）。

    语料 §5.2 的真值表原本假设：无关素材下 reflect 判 `end`（判不出矛盾）。
    **实测不成立** —— 面对明显不相关的素材，生产 prompt 里的
    `re_iterate`（"素材不够 / 需要再查"，`reflect_prompt.py:53`）才是语义正确的出口。

    → 两类格子测的根本不是一件事：
    - **标准素材（24 格）**：素材充分 → reflect 判「答案 vs 素材」→ **忠实性判别力**
    - **无关素材（24 格）**：素材明显不对 → reflect 判「素材够不够」→ **素材充分性判别力**

    本函数把两条轴分开算，**不替换** §7.3 的口径 —— 两套数字都报，差别由人判断。
    """
    out = {}
    for kind in ("standard", "irrelevant"):
        sub = [r for r in rows if r.get("material_kind") == kind]
        b = {}
        for r in sub:
            r.setdefault("bucket", classify(r))
            b[r["bucket"]] = b.get(r["bucket"], 0) + 1
        tp_total = b.get("tp_hit", 0) + b.get("tp_miss", 0)
        tn_total = b.get("tn_fp", 0) + b.get("tn_ok", 0)
        ud_total = b.get("ud_ok", 0) + b.get("ud_over", 0)
        n_err = b.get("error", 0)
        n_judged = len(sub) - n_err
        out[kind] = {
            "n": len(sub),
            "judged": n_judged,
            "errors": n_err,
            "counts": b,
            "true_positive_total": tp_total,
            "true_positive_rate": (b.get("tp_hit", 0) / tp_total) if tp_total else None,
            "false_positive_total": tn_total,
            "false_positive_rate": (b.get("tn_fp", 0) / tn_total) if tn_total else None,
            "undetermined_total": ud_total,
            "undetermined_rate": (b.get("ud_ok", 0) / ud_total) if ud_total else None,
            # 素材充分性轴：无关素材下判 re_iterate = 看出素材不对，要再查
            "re_iterate_rate": (b.get("anomaly_re_iterate", 0) / n_judged) if n_judged else None,
        }
    return out


def breakdown(rows, key):
    """按某个字段分组的判定明细（用于 good-1 / good-2 引用维度对照）。"""
    out = {}
    for r in rows:
        k = r.get(key)
        out.setdefault(k, {"n": 0, "rewrite": 0, "end": 0, "re_iterate": 0, "other": 0})
        out[k]["n"] += 1
        if r.get("bucket") == "error":
            continue
        if r.get("action") == "rewrite":
            out[k]["rewrite"] += 1
        elif r.get("action") == "end":
            out[k]["end"] += 1
        elif r.get("action") == "re_iterate":
            out[k]["re_iterate"] += 1
        else:
            out[k]["other"] += 1
    return out


# --------------------------------------------------------------------------
# 重复遍数的聚合（设计稿 §7.5：3 遍取众数 → 报均值 + 单次分布）
# --------------------------------------------------------------------------
def summarize_by_repeat(rows):
    """每一遍单独汇总 —— 不把多遍糊成一个池子。

    一遍 = 一次**独立**判定（reflect 重新调一次 LLM）。
    池化会把"某些格子时灵时不灵"藏起来 → 数字要能写进简历，必须先看到单次分布。
    """
    reps = sorted({r.get("repeat") for r in rows if r.get("repeat") is not None})
    out = []
    for r in reps:
        s = summarize([x for x in rows if x.get("repeat") == r])
        s["repeat"] = r
        out.append(s)
    return out


def _stat(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {
        "mean": round(sum(vals) / len(vals), 4),
        "min": min(vals),
        "max": max(vals),
        "spread": round(max(vals) - min(vals), 4),
        "values": vals,
    }


def summarize_across_repeats(by_repeat):
    """跨遍统计：均值 + 极差。"""
    if not by_repeat:
        return {}
    return {
        "repeats": len(by_repeat),
        "true_positive_rate": _stat([s.get("true_positive_rate") for s in by_repeat]),
        "false_positive_rate": _stat([s.get("false_positive_rate") for s in by_repeat]),
        "undetermined_rate": _stat([s.get("undetermined_rate") for s in by_repeat]),
        "anomaly_re_iterate": [s.get("anomaly_re_iterate") for s in by_repeat],
        "errors": [s.get("errors") for s in by_repeat],
        "counts_per_repeat": [s.get("counts") for s in by_repeat],
    }


def case_consensus(rows):
    """逐用例共识：多遍判定是否一致，众数是什么。

    不一致 = 这个格子本身不稳 → 它的指标就不该被当成硬结论。
    """
    out = {}
    for cid in sorted({r["id"] for r in rows}):
        ds = [r for r in rows if r["id"] == cid]
        acts = [r.get("action") for r in ds if r.get("bucket") != "error"]
        row = {"repeats": len(ds), "actions": acts}
        if acts:
            freq = {}
            for a in acts:
                freq[a] = freq.get(a, 0) + 1
            best = max(freq.values())
            cands = sorted(k for k, n in freq.items() if n == best)
            row["majority"] = cands[0]
            row["stable"] = len(cands) == 1
            row["tie"] = len(cands) > 1
        out[cid] = row
    return out


# --------------------------------------------------------------------------
# 第二轮：改后改善率（--improve）
# --------------------------------------------------------------------------
def run_improve(rows, cases_by_id, aq_cases, executor_model):
    """判了 rewrite 的用例 → synth 重写 → 用线 A 的尺子重新打分。

    复用线 A 的判分器（`judge_answer_quality.py`）和 B 组 `must_contain`：
    原始候选答案与重写后的答案用**同一把尺子**，改善量才可比。
    """
    from importlib import import_module

    from judge_answer_quality import judge_case

    synth_node_mod = import_module("agent.nodes.synth_node")

    llm = synth_node_mod._get_llm()
    aq_by_id = {c["id"]: c for c in aq_cases}

    improved, details = [], []
    # 多遍时同一个用例会出现多次 → 按 id 取**众数判定**的那一条，只重写一次
    by_id = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    reps = []
    for cid, ds in by_id.items():
        acts = [d.get("action") for d in ds if d.get("bucket") != "error"]
        if not acts:
            continue
        freq = {}
        for a in acts:
            freq[a] = freq.get(a, 0) + 1
        best = max(freq.values())
        maj = sorted(k for k, n in freq.items() if n == best)[0]
        pick = next(d for d in ds if d.get("action") == maj)
        pick = dict(pick)
        pick["id"] = cid
        pick["action"] = maj
        reps.append(pick)

    for r in reps:
        if r.get("action") != "rewrite":
            continue
        case = cases_by_id[r["id"]]
        aq = aq_by_id.get(case["question_id"])
        if aq is None:
            continue

        state = build_state(aq["query"], case["material"], case["answer"])
        state["last_critique"] = r.get("critique") or ""
        try:
            out = synth_node_mod.synth_node(state, llm=llm)
            rewritten = out.get("last_answer") or ""
        except Exception as e:
            details.append({
                "id": r["id"], "error": f"synth 失败：{type(e).__name__}: {e}",
            })
            continue

        before = judge_case(aq, case["answer"])
        after = judge_case(aq, rewritten)
        d_hit = (
            (after.get("hit_rate") or 0) - (before.get("hit_rate") or 0)
            if after.get("hit_rate") is not None and before.get("hit_rate") is not None
            else None
        )
        rec = {
            "id": r["id"],
            "question_id": case["question_id"],
            "hit_rate_before": before.get("hit_rate"),
            "hit_rate_after": after.get("hit_rate"),
            "hit_rate_delta": d_hit,
            "halluc_before": before.get("halluc"),
            "halluc_after": after.get("halluc"),
            "rewritten_len": len(rewritten),
        }
        details.append(rec)
        if d_hit is not None:
            improved.append(d_hit)

    return {
        "n": len(details),
        "mean_hit_rate_delta": (sum(improved) / len(improved)) if improved else None,
        "n_improved": sum(1 for d in improved if d > 0),
        "n_unchanged": sum(1 for d in improved if d == 0),
        "n_worse": sum(1 for d in improved if d < 0),
        "details": details,
    }


# --------------------------------------------------------------------------
# 快照 & 报告
# --------------------------------------------------------------------------
def _unique_path(path: Path) -> Path:
    """快照永不覆盖：同名就加 -2 / -3 后缀。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 2
    while True:
        cand = path.with_name(f"{stem}-{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def file_sha256(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_commit():
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]),
        ).stdout.strip()
    except Exception:
        return None


def print_report(rows, summary, axis=None, improve=None, by_repeat=None, across=None, consensus=None):
    print()
    print("=" * 78)
    print("线 B 反思消融 · 单格判定")
    print("=" * 78)
    if by_repeat and len(by_repeat) > 1:
        _print_repeat_view(by_repeat, across, consensus)
        print()
        print("=" * 78)
        print("线 B 反思消融 · 单格判定（逐遍）")
        print("=" * 78)
    print(f"{'用例':<18}{'期望':<10}{'实际':<12}{'桶':<12}说明")
    for r in rows:
        mark = {"tp_hit": "✅", "tp_miss": "❌", "tn_ok": "✅", "tn_fp": "⚠️",
                "ud_ok": "⚪", "ud_over": "⚠️", "anomaly_re_iterate": "🚩",
                "error": "💥"}.get(r["bucket"], "?")
        note = (r.get("critique") or "").replace("\n", " ")[:44]
        print(f"{mark} {r['id']:<16}{r['expect_action']:<10}{str(r['action']):<12}"
              f"{r['bucket']:<12}{note}")
        if r.get("error"):
            print(f"    错误：{r['error']}")

    print()
    print("=" * 78)
    print("四个指标（设计稿 §7.3）")
    print("=" * 78)

    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"

    print(f"  真阳性率    {pct(summary['true_positive_rate']):>7}"
          f"   （{summary['counts'].get('tp_hit', 0)}/{summary['true_positive_total']}）"
          f"   越高越好")
    print(f"  假阳性率    {pct(summary['false_positive_rate']):>7}"
          f"   （{summary['counts'].get('tn_fp', 0)}/{summary['false_positive_total']}）"
          f"   越低越好")
    print(f"  不可判定率  {pct(summary['undetermined_rate']):>7}"
          f"   （{summary['counts'].get('ud_ok', 0)}/{summary['undetermined_total']}）"
          f"   已知边界，不追求降低")
    if summary["anomaly_re_iterate"]:
        print(f"  ⚠️ re_iterate 异常 {summary['anomaly_re_iterate']} 例"
              f"（语料 §7：线 B 恒为 success，出现即异常，不并进上面三个指标）")
    if summary["errors"]:
        print(f"  ⚠️ 判分故障 {summary['errors']} 例（已从分母剔除）")

    print()
    print("  按答案类型（判定分布）：")
    for kind, v in sorted(breakdown(rows, "answer_kind").items()):
        print(f"    {kind:<14} rewrite {v['rewrite']}/{v['n']}"
              f"   end {v['end']}   re_iterate {v['re_iterate']}   other {v['other']}")
    print("  按素材类型：")
    for kind, v in sorted(breakdown(rows, "material_kind").items()):
        print(f"    {kind:<14} rewrite {v['rewrite']}/{v['n']}"
              f"   end {v['end']}   re_iterate {v['re_iterate']}   other {v['other']}")

    if axis:
        print()
        print("=" * 78)
        print("按素材类型拆成两条轴（【实测】语料 §5.2 的真值表在无关素材上不成立）")
        print("=" * 78)
        std, irr = axis["standard"], axis["irrelevant"]
        print("  轴一 · 标准素材（素材充分 → 测「答案 vs 素材」= 忠实性判别力）")
        print(f"    真阳性率    {pct(std['true_positive_rate']):>7}"
              f"   （{std['counts'].get('tp_hit', 0)}/{std['true_positive_total']}）")
        print(f"    假阳性率    {pct(std['false_positive_rate']):>7}"
              f"   （{std['counts'].get('tn_fp', 0)}/{std['false_positive_total']}）")
        print(f"    不可判定率  {pct(std['undetermined_rate']):>7}"
              f"   （{std['counts'].get('ud_ok', 0)}/{std['undetermined_total']}）")
        print("  轴二 · 无关素材（素材明显不对 → 测「素材够不够」= 素材充分性判别力）")
        print(f"    判 re_iterate（看出素材不对、要再查）{pct(irr['re_iterate_rate'])}"
              f"   （{irr['counts'].get('anomaly_re_iterate', 0)}/{irr['judged']}）")
        print(f"    判 end（没看出素材不对）        {irr['counts'].get('tn_ok', 0) + irr['counts'].get('ud_ok', 0)}"
              f"      判 rewrite {irr['counts'].get('tn_fp', 0) + irr['counts'].get('tp_hit', 0)}")
        print("    → 这条轴的产出不是「忠实性真阳性」，是「素材够不够」——"
              "语料 §5.2 原本把这两类格子混在一张表里算")

    # good-1（无引用）vs good-2（带引用）—— 分离"忠实性误报"与"引用规则生效"
    g1 = [r for r in rows if r["id"].endswith("-1-S") and r["answer_kind"] == "good"]
    g2 = [r for r in rows if r["id"].endswith("-2-S") and r["answer_kind"] == "good"]
    if g1 and g2:
        n1 = sum(1 for r in g1 if r.get("action") == "rewrite")
        n2 = sum(1 for r in g2 if r.get("action") == "rewrite")
        print()
        print(f"  引用维度对照（good-1 不带引用 / good-2 带引用，均为标准素材）：")
        print(f"    good-1 判 rewrite {n1}/{len(g1)}    good-2 判 rewrite {n2}/{len(g2)}")
        if n1 > n2:
            print("    → good-1 更容易被改：疑似是 REFLECT_PROMPT 的引用规则生效，"
                  "不是忠实性误报")
        elif n1 < n2:
            print("    → good-2 更容易被改：与设计的引用规则相反，值得单独查")
        else:
            print("    → 两者一致：引用规则未成为混杂因素")

    if improve:
        print()
        print("=" * 78)
        print("改后改善率（第二轮 · --improve）")
        print("=" * 78)
        print(f"  样本 {improve['n']} 条（第一轮判了 rewrite 的用例）")
        delta = improve["mean_hit_rate_delta"]
        delta_txt = "—" if delta is None else f"{delta:+.3f}"
        print(f"  平均 hit_rate 变化：{delta_txt}")
        print(f"  变好 {improve['n_improved']} · 不变 {improve['n_unchanged']}"
              f" · 变差 {improve['n_worse']}")
        for d in improve["details"]:
            if d.get("error"):
                print(f"    {d['id']}: {d['error']}")
            else:
                print(f"    {d['id']:<16} {d['hit_rate_before']} → {d['hit_rate_after']}"
                      f"  （{d['hit_rate_delta']:+.3f}）"
                      + (f"  幻觉 {d['halluc_before']}→{d['halluc_after']}"
                         if d["halluc_before"] != d["halluc_after"] else ""))


def _print_repeat_view(by_repeat, across, consensus):
    """多遍视图：单次分布 + 跨遍统计 + 不稳的格子。"""
    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"

    print()
    print("=" * 78)
    print("多遍视图（每遍 = 一次独立 reflect 判定）")
    print("=" * 78)
    print(f"{'遍':<5}{'真阳性率':<12}{'假阳性率':<12}{'不可判定率':<14}{'re_iterate':<12}{'故障':<6}")
    for s in by_repeat:
        print(f"{s['repeat']:<5}{pct(s.get('true_positive_rate')):<12}"
              f"{pct(s.get('false_positive_rate')):<12}"
              f"{pct(s.get('undetermined_rate')):<14}"
              f"{str(s.get('anomaly_re_iterate')):<12}{str(s.get('errors')):<6}")

    print()
    for key, label in (("true_positive_rate", "真阳性率"),
                       ("false_positive_rate", "假阳性率"),
                       ("undetermined_rate", "不可判定率")):
        st = (across or {}).get(key)
        if not st:
            continue
        print(f"{label:<12} 均值 {pct(st['mean'])}   最小 {pct(st['min'])}"
              f"   最大 {pct(st['max'])}   极差 {pct(st['spread'])}")

    unstable = [cid for cid, v in (consensus or {}).items() if not v.get("stable", True)]
    if unstable:
        print()
        print(f"⚠️ 多遍判定不一致的格子（{len(unstable)}/{len(consensus or {})}）—— "
              f"这些格子的指标不该当硬结论：")
        for cid in unstable:
            v = consensus[cid]
            print(f"    {cid:<18} 各遍 = {v['actions']}   众数 = {v.get('majority')}")
    print()
    print("⚠️ 单次采样有 LLM 随机性 → 均值是本次多遍的估计，不是稳定基线。")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="线 B 反思消融评测")
    ap.add_argument("--repeat", type=int, default=1, help="每个用例重复几遍（默认 1）")
    ap.add_argument("--improve", action="store_true",
                    help="第二轮：跑改后改善率（额外消耗 LLM）")
    ap.add_argument("--only", default="", help="只跑某些题号，逗号分隔，如 B01,B02")
    args = ap.parse_args()

    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    aq_cases = json.loads(AQ_CASE_FILE.read_text(encoding="utf-8"))["cases"]

    # 题目文本以线 A 的 case 文件为准（单一来源，且已核对过题集）
    aq_by_id = {c["id"]: c for c in aq_cases}
    for c in cases:
        aq = aq_by_id.get(c["question_id"])
        if aq is None:
            print(f"❌ {c['id']}：线 A case 文件里没有 {c['question_id']}")
            return 1
        c["_query"] = aq["query"]

    if args.only:
        keep = {s.strip() for s in args.only.split(",") if s.strip()}
        cases = [c for c in cases if c["question_id"] in keep]
        print(f"只跑 {sorted(keep)}：{len(cases)} 个用例 × {args.repeat} 遍")

    print(f"线 B 反思消融 · 执行体 {EXECUTOR_MODEL} · {len(cases)} 用例 × {args.repeat} 遍")
    print("（判分直接是 reflect 的 next_action，线 B 不需要判分器）")
    print()

    llm = _get_executor_llm()
    rows = []
    for i, c in enumerate(cases, 1):
        for rep in range(args.repeat):
            r = run_case(c, c["_query"], llm, EXECUTOR_MODEL)
            r["repeat"] = rep + 1
            r["bucket"] = classify(r)
            rows.append(r)
            print(f"  [{i:>2}/{len(cases)}] 第 {rep + 1}/{args.repeat} 遍 "
                  f"{r['id']:<16} 期望 {r['expect_action']:<8}"
                  f"实际 {str(r['action']):<10}", flush=True)

    summary = summarize(rows)
    axis = summarize_by_axis(rows)
    by_repeat = summarize_by_repeat(rows)
    across = summarize_across_repeats(by_repeat)
    consensus = case_consensus(rows)

    improve = None
    if args.improve:
        print()
        print("第二轮：改后改善率（synth 重写 + 线 A 判分器）…", flush=True)
        cases_by_id = {c["id"]: c for c in cases}
        improve = run_improve(rows, cases_by_id, aq_cases, EXECUTOR_MODEL)

    print_report(rows, summary, axis, improve, by_repeat, across, consensus)

    # 快照（永不覆盖）
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    path = _unique_path(out_dir / f"reflect_ablation_{_today()}.json")
    payload = {
        "meta": {
            "date": _today(),
            "git_commit": git_commit(),
            "cases_file_sha256": file_sha256(CASE_FILE),
            "executor_model": EXECUTOR_MODEL,
            "judge_model": JUDGE_MODEL if args.improve else None,
            "repeat": args.repeat,
            "total_cases": len(cases),
            "notes": "线 B 判分直接取 reflect 的 next_action；"
                     "不可判定单独统计，不与真阳性混算",
        },
        "summary": summary,
        "by_axis": axis,
        "by_repeat": by_repeat,
        "across_repeats": across,
        "case_consensus": consensus,
        "improvement": improve,
        "details": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n快照：{path}")


def _today():
    import datetime

    return datetime.date.today().isoformat()


if __name__ == "__main__":
    sys.exit(main())

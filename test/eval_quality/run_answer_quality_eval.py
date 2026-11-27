"""test/eval_quality/run_answer_quality_eval.py —— 线 A 端到端答案质量评测。

测什么
------
12 道题走**生产 Agent 图**（`agent/graph.py` 的 `build_graph()`，一行代码没改），
拿到最终答案，再交给判分器（`judge_answer_quality.py`，MiniMax-M2.5）判分，汇总成一份可复算的数字。

三种模式
--------
```
python test/eval_quality/run_answer_quality_eval.py --recall-check   # 只跑召回前提检查（不调 LLM）
python test/eval_quality/run_answer_quality_eval.py                   # 跑全套（Agent + 判分 + 汇总 + 快照）
python test/eval_quality/run_answer_quality_eval.py --closed-book      # 闭卷准入探针（裸问模型，无检索）
```

口径（设计稿 §6）
----------------
- 单题分 `score_i = 0.6×hit_rate + 0.3×(1−halluc) + 0.1×retrieval_hit`
- **硬闸门**：`halluc=1` → `score_i` 封顶 0.5（幻觉率跨题稀释，权重公式会放过一个胡编的答案）
- **总分只由 A/B 组 8 题算**（`mean(score_i)`）；C/D 组是二值附加指标，不进总分
- `depth_rate`（深度率）**不进总分**，单独报 —— 它看的是"有没有主动多说一层"，不是"答没答到题"
- `hit_rate` 分母是 **24 条** `must_contain`（不是 24 题）；`depth_rate` 分母是 **6 条** `should_contain`

复算信息（每份快照必带，设计稿 §11）
--------------------------------------
`corpus_sha256` / `git_commit` / `rubric_version` / `executor_model` / `judge_model` / `cases_hash`
+ 逐题明细（query / retrieved_chunks / answer / hit_rate / halluc / retrieval_hit / raw_judge_output）

**快照永不覆盖** —— 同名已存在就加 `-2` / `-3` 后缀。

为什么不用 `agent.runtime.ask()`
-------------------------------
`ask()` 只回 5 个字段（answer / iter_count / reflection_count / tool_called / last_action），
拿不到「调了哪些工具」「检索到了什么」—— 而 C02 要记「有没有调 weather 工具」、
`retrieval_hit` 要拿真实召回片段。所以这里直接用**同一张生产图** `build_graph()`，
`invoke` 的入参跟 `runtime.ask()` 完全一致（`messages` + `deadline` + `recursion_limit`），
产品代码一行没改。
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 仓库根 = eval_quality/ → test/ → <repo>
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.constants import TOTAL_TIMEOUT
from agent.graph import build_graph
from agent.runtime import RECURSION_LIMIT, _extract_answer
from judge_answer_quality import judge_case, load_cases
from utils.models.model_setting import LLMmodel

HERE = Path(__file__).resolve().parent
CASE_FILE = HERE / "data" / "answer_quality_cases.json"
RESULT_DIR = HERE / "results"

EXECUTOR_MODEL = "MiniMax-M3.1-Flash"
JUDGE_MODEL = "MiniMax-M2.5"

W_HIT, W_HALLUC, W_RETR = 0.6, 0.3, 0.1
HALLUC_CAP = 0.5
# rag_tool.py 用这个分隔符拼 chunk
CHUNK_SEP = "\n\n---\n\n"


# --------------------------------------------------------------------------
# 复算信息
# --------------------------------------------------------------------------
def corpus_sha256():
    """txt/*.txt 全部文件按文件名排序、原始字节拼接后的 sha256。

    实测这个算法得到的值 = 设计稿 §8.3 记录的 eae9bb07…（同语料同值）。
    """
    files = sorted((Path.cwd() / "txt").glob("*.txt"), key=lambda p: p.name)
    h = hashlib.sha256()
    for p in files:
        h.update(p.read_bytes())
    return h.hexdigest()


def git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(Path.cwd()),
        ).stdout.strip()
    except Exception:
        return ""


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def today():
    return datetime.now().strftime("%Y-%m-%d")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 跑 Agent
# --------------------------------------------------------------------------
def _tool_telemetry(messages):
    """从图返回的 messages 里扒出：调了哪些工具、rag_search 召回了什么。

    额外记下**Agent 实际发出的查询**（`rag_search` 的 args）——
    模型会自己改写查询，改写后的召回可能比原问题直接检索更差，
    不记下来就只能靠猜。
    """
    call_id_to_name = {}
    tools_called = []
    queries = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                name = tc.get("name")
                tools_called.append(name)
                if name == "rag_search":
                    q = (tc.get("args") or {}).get("query")
                    queries.append(q if isinstance(q, str) else str(q))
                if tc.get("id"):
                    call_id_to_name[tc["id"]] = name

    chunks = []
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        name = call_id_to_name.get(getattr(m, "tool_call_id", ""), "") or getattr(m, "name", "")
        if name != "rag_search":
            continue
        content = m.content
        if isinstance(content, list):  # 多模态形态
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        if content:
            chunks.extend(content.split(CHUNK_SEP))
    return tools_called, chunks, queries


def run_agent(query):
    """跑一次生产 Agent 图，返回 (答案, telemetry)。异常不外抛。"""
    graph = build_graph()
    started = time.time()
    try:
        result = graph.invoke(
            {
                "messages": [HumanMessage(query)],
                "deadline": time.time() + TOTAL_TIMEOUT,
            },
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except Exception as e:
        return "", {
            "error": f"{type(e).__name__}: {e}",
            "elapsed": round(time.time() - started, 1),
            "tools_called": [],
            "queries": [],
            "chunks": [],
        }

    messages = result.get("messages", [])
    answer = _extract_answer(messages)
    tools_called, chunks, queries = _tool_telemetry(messages)
    return answer, {
        "error": None,
        "elapsed": round(time.time() - started, 1),
        "iter_count": result.get("iter_count"),
        "reflection_count": result.get("reflection_count"),
        "last_action": result.get("next_action"),
        "queries": queries,
        "tool_status": result.get("tool_status", {}),
        "tools_called": tools_called,
        "chunks": chunks,
    }


# --------------------------------------------------------------------------
# 召回锚点检查（§8.2）
# --------------------------------------------------------------------------
def check_anchors(case, chunks):
    """按锚点正则检查召回片段。返回 (命中数, 总数, 逐条明细)。

    ⚠️ 必须用**带上下文的正则**，不能用裸 token —— 实测 `"30" in "300"` 是假阳性。
    """
    anchors = case.get("anchors") or []
    if not anchors:
        return None, None, []
    joined = "\n".join(chunks)
    rows = []
    for a in anchors:
        found = bool(re.search(a["regex"], joined))
        expect = a.get("expect", "hit")
        ok = found if expect == "hit" else (not found)
        rows.append({
            "name": a["name"],
            "expect": expect,
            "found": found,
            "ok": ok,
        })
    hit = sum(1 for r in rows if r["ok"])
    return hit, len(rows), rows


def retrieval_hit_flag(case, chunks):
    """retrieval_hit：这道题要的锚点内容**全都**在召回片段里 = 1。

    A/B 组才有意义；C01 的锚点期望 0 命中（语料外探针）、C02/D 不依赖检索 → 不计。
    """
    if not case.get("scored"):
        return None
    hit, total, _ = check_anchors(case, chunks)
    if not total:
        return None
    return 1 if hit == total else 0


# --------------------------------------------------------------------------
# 打分
# --------------------------------------------------------------------------
def score_case(case, res, telemetry):
    """按题型算分。A/B 组走加权公式 + 幻觉闸门；C/D 组是二值。"""
    if not case.get("scored"):
        return {
            "score": None,
            "hit_rate": res.get("hit_rate"),
            "halluc": res.get("halluc"),
            "retrieval_hit": None,
            "depth_rate": res.get("depth_rate"),
            "binary_pass": res.get("pass"),
        }

    hit = res.get("hit_rate")
    halluc = res.get("halluc")
    retr = telemetry.get("retrieval_hit")
    if hit is None or halluc is None:
        return {"score": None, "hit_rate": hit, "halluc": halluc,
                "retrieval_hit": retr, "depth_rate": res.get("depth_rate"),
                "binary_pass": None}

    score = W_HIT * hit + W_HALLUC * (1 - halluc)
    if retr is not None:
        score += W_RETR * retr
    if halluc == 1:
        score = min(score, HALLUC_CAP)
    return {
        "score": round(score, 4),
        "hit_rate": hit,
        "halluc": halluc,
        "retrieval_hit": retr,
        "depth_rate": res.get("depth_rate"),
        "binary_pass": None,
    }


def summarize(details, cases_by_id):
    """汇总。总分只由 A/B 组算；C/D 组单独报。

    ⚠️ 分母口径：**判分器故障的题不进分母**（`judge_answer_quality.py::judge_case`
    把故障记成 `judge_error` + `hit_rate=None`）—— 判分器坏 ≠ 答案错，
    不能当 0 分算进去。正常情况下分母就是 24 条必答 / 6 条深度。
    """
    ab = [d for d in details if cases_by_id[d["id"]].get("scored")]
    scored = [d for d in ab if d.get("score") is not None]

    # `must_hits` 是布尔列表，`must_hit_count` 才是命中条数
    judged = [d for d in ab if d.get("must_hit_count") is not None]
    must_hits = sum(d["must_hit_count"] for d in judged)
    must_total = sum(len(cases_by_id[d["id"]]["must_contain"]) for d in judged)
    depth_judged = [d for d in ab if d.get("depth_hits") is not None]
    depth_hits = sum(d["depth_hits"] for d in depth_judged)
    depth_total = sum(len(cases_by_id[d["id"]]["should_contain"]) for d in depth_judged)
    halluc_cases = [d["id"] for d in ab if d.get("halluc") == 1]
    retr_hits = [d for d in ab if d.get("retrieval_hit") == 1]

    out = {
        "total_score": round(sum(d["score"] for d in scored) / len(scored), 4) if scored else None,
        "scored_questions": len(scored),
        "total_questions": len(ab),
        "hit_rate": round(must_hits / must_total, 4) if must_total else None,
        "must_hits": must_hits,
        "must_total": must_total,
        "depth_rate": round(depth_hits / depth_total, 4) if depth_total else None,
        "depth_hits": depth_hits,
        "depth_total": depth_total,
        "halluc_cases": halluc_cases,
        "halluc_count": len(halluc_cases),
        "retrieval_hit_rate": round(len(retr_hits) / len(ab), 4) if ab else None,
    }

    for d in details:
        c = cases_by_id[d["id"]]
        if c["type"] == "honesty":
            out.setdefault("honesty_pass", {})[d["id"]] = d.get("binary_pass")
        elif c["type"] == "placeholder_honesty":
            out.setdefault("placeholder_marker_retention", {})[d["id"]] = d.get("binary_pass")
            out.setdefault("weather_tool_called", {})[d["id"]] = d.get("weather_tool_called")
        elif c["type"] == "tool":
            out.setdefault("tool_answer_correct", {})[d["id"]] = d.get("binary_pass")
            out.setdefault("tool_detail", {})[d["id"]] = {
                "number_ok": d.get("number_ok"),
                "tool_ok": d.get("tool_ok"),
                "extracted_numbers": d.get("extracted_numbers"),
                "last_number": d.get("last_number"),
            }
    return out


# --------------------------------------------------------------------------
# 重复遍数的聚合（设计稿 §7.5：3 遍取众数 → 报均值 + 单次分布）
# --------------------------------------------------------------------------
def summarize_by_repeat(details, cases_by_id):
    """每一遍单独汇总一遍 —— 不把 3 遍糊成一个池子。

    一遍 = 一次**独立**评测：Agent 重新调、LLM 重新生成、判分器重新判。
    池化的数字会把「不稳定」藏起来（实测两遍总分 0.925 ↔ 0.9875，
    C01/C02 的二值判定直接翻转）→ 数字要能写进简历，必须先看到单次分布。
    """
    reps = sorted({d.get("repeat") for d in details if d.get("repeat")})
    out = []
    for r in reps:
        s = summarize([d for d in details if d.get("repeat") == r], cases_by_id)
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
    """跨遍统计：均值 + 极差 + 每题的通过遍数。"""
    if not by_repeat:
        return {}
    out = {
        "repeats": len(by_repeat),
        "total_score": _stat([s.get("total_score") for s in by_repeat]),
        "hit_rate": _stat([s.get("hit_rate") for s in by_repeat]),
        "depth_rate": _stat([s.get("depth_rate") for s in by_repeat]),
        "retrieval_hit_rate": _stat([s.get("retrieval_hit_rate") for s in by_repeat]),
        "halluc_per_repeat": [s.get("halluc_cases") for s in by_repeat],
        "denominator_per_repeat": [
            {"repeat": s.get("repeat"), "must_total": s.get("must_total"),
             "depth_total": s.get("depth_total"), "scored_questions": s.get("scored_questions")}
            for s in by_repeat
        ],
    }
    for key, label in (("honesty_pass", "honesty"),
                       ("placeholder_marker_retention", "placeholder"),
                       ("tool_answer_correct", "tool")):
        if key not in by_repeat[0]:
            continue
        per_id = {}
        for sid in by_repeat[0][key]:
            vals = [s.get(key, {}).get(sid) for s in by_repeat]
            passed = sum(1 for v in vals if v is True)
            per_id[sid] = {
                "pass_repeats": passed,
                "total_repeats": len(vals),
                "values": vals,
                "majority": (True if passed * 2 > len(vals)
                             else False if passed * 2 < len(vals) else None),
            }
        out[label + "_by_repeat"] = per_id
    return out


def question_consensus(details, cases_by_id):
    """逐题共识：3 遍的命中条数 / 分数，以及众数。

    众数取「出现次数最多」；打平时取**更小的那个**（保守），
    并把 tie 标出来 —— 打平本身就是「这题不稳」的信号。
    """
    out = {}
    for qid in sorted({d["id"] for d in details}):
        ds = [d for d in details if d["id"] == qid]
        hits = [d.get("must_hit_count") for d in ds if d.get("must_hit_count") is not None]
        scores = [d.get("score") for d in ds if d.get("score") is not None]
        binary = [d.get("binary_pass") for d in ds if d.get("binary_pass") is not None]
        row = {
            "repeats": len(ds),
            "must_hit_counts": hits,
            "must_total": ds[0].get("must_total"),
            "scores": scores,
            "halluc": [d.get("halluc") for d in ds],
            "retrieval_hit": [d.get("retrieval_hit") for d in ds],
        }
        if hits:
            freq = {}
            for h in hits:
                freq[h] = freq.get(h, 0) + 1
            best = max(freq.values())
            cands = sorted(h for h, n in freq.items() if n == best)
            row["consensus_hits"] = cands[0]
            row["tie"] = len(cands) > 1
        if scores:
            freq = {}
            for h in scores:
                freq[h] = freq.get(h, 0) + 1
            best = max(freq.values())
            cands = sorted(h for h, n in freq.items() if n == best)
            row["consensus_score"] = cands[0]
            row["score_tie"] = len(cands) > 1
        if binary:
            row["binary_values"] = binary
            row["consensus_binary"] = True if sum(binary) * 2 > len(binary) else (
                False if sum(binary) * 2 < len(binary) else None)
        out[qid] = row
    return out


# --------------------------------------------------------------------------
# 模式一：召回前提检查（准入，不调 LLM）
# --------------------------------------------------------------------------
def mode_recall_check(cases):
    from agent.tools.rag_tool import _ensure_rag

    rag = _ensure_rag()
    print("召回前提检查（生产检索路径 RagModel.retrieve(query, top_k=5)）\n")
    rows, failed = [], []
    for case in cases:
        if not case.get("anchors"):
            continue
        chunks = rag.retrieve(case["query"], top_k=5)
        hit, total, detail = check_anchors(case, chunks)
        ok = hit == total
        if not ok:
            failed.append(case["id"])
        rows.append((case["id"], hit, total, ok, detail))
        mark = "✅" if ok else "❌"
        print(f"  {mark} {case['id']}  锚点命中 {hit}/{total}")
        for d in detail:
            if not d["ok"]:
                print(f"       未通过：{d['name']}（期望 {d['expect']}，实际 {'命中' if d['found'] else '未命中'}）")
    print()
    if failed:
        print(f"❌ 召回前提不成立：{', '.join(failed)} —— 这些题测的是检索运气，不是答案质量（设计稿 §8）")
        return 1
    print("✅ 全部题目的召回前提成立")
    return 0


# --------------------------------------------------------------------------
# 模式二：闭卷准入探针（裸问模型，无检索、无 Agent）
# --------------------------------------------------------------------------
CLOSED_BOOK_SYSTEM = "请如实回答下面的问题。"


def mode_closed_book(cases):
    """裸问模型同一个问题，看它不查资料能不能答对 → 判分 → 命中哪些要点。

    用途是**题集准入**：闭卷能力是**题目的属性**（同一道题在不同时刻的先验可猜性不会变），
    所以跑一次就够，不需要每轮评测都重跑。

    ⚠️ 注意：设计稿 §6.5 原来的形态（「工具被禁用」）**测不出东西** —— 实测
    `iter_prompt.py:17` 把 `调用 rag_search` 写死在决策规则里，工具禁用了模型照样发调用，
    ToolNode 回一句「rag_search is not a valid tool」，synth 节点于是产出
    「工具调用异常 / 未在文档中找到 / 直接用通用知识作答」三种完全不同的东西 ——
    它测的是「工具失败时模型诚实吗」，不是「这题能不能不查就答对」。形态和目的对不上。
    """
    llm = LLMmodel.create_minimax(
        EXECUTOR_MODEL, temperature=0.7, max_tokens=8192, timeout=120
    ).chat

    print(f"闭卷准入探针（裸问 {EXECUTOR_MODEL}，无检索 / 无 Agent / 无项目上下文）\n")
    rows = []
    for case in cases:
        if not case.get("scored"):
            continue
        started = time.time()
        try:
            resp = llm.invoke([
                HumanMessage(content=CLOSED_BOOK_SYSTEM),
                HumanMessage(content=case["query"]),
            ])
            answer = resp.content if isinstance(resp.content, str) else str(resp.content)
            err = None
        except Exception as e:
            answer, err = "", f"{type(e).__name__}: {e}"
        res = judge_case(case, answer) if not err else {"hit_rate": None, "judge_error": err}
        rows.append({
            "id": case["id"],
            "query": case["query"],
            "answer": answer,
            "hit_rate": res.get("hit_rate"),
            "depth_rate": res.get("depth_rate"),
            "halluc": res.get("halluc"),
            "must_hits": res.get("must_hits"),
            "must_reasons": res.get("must_reasons"),
            "error": err or res.get("judge_error"),
            "elapsed": round(time.time() - started, 1),
        })
        print(f"  {case['id']}  闭卷 hit_rate={res.get('hit_rate')}  ({rows[-1]['elapsed']}s)")

    print()
    print("判读：闭卷 hit_rate 高的题 = 不查资料也能答对的题 → 需要改问法或剔除（设计稿 R7）")
    out = {
        "created_at": now_iso(),
        "executor_model": EXECUTOR_MODEL,
        "judge_model": JUDGE_MODEL,
        "cases_hash": file_sha256(CASE_FILE),
        "rows": rows,
    }
    path = _unique_path(RESULT_DIR / f"closed_book_probe_{today()}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n快照：{path}")
    return 0


# --------------------------------------------------------------------------
# 模式三：全套
# --------------------------------------------------------------------------
def mode_full(cases, repeat=1, only=None):
    results = []
    for r in range(repeat):
        for case in cases:
            if only and case["id"] not in only:
                continue
            print(f"[{case['id']}] 跑 Agent（第 {r + 1}/{repeat} 遍）…", flush=True)
            answer, tel = run_agent(case["query"])
            tel["retrieval_hit"] = retrieval_hit_flag(case, tel["chunks"])
            ahit, atotal, adetail = check_anchors(case, tel["chunks"])
            tel["anchor_hits"] = ahit
            tel["anchor_total"] = atotal
            tel["anchor_detail"] = adetail
            print(f"     工具={tel['tools_called']} 耗时={tel['elapsed']}s "
                  f"锚点={ahit}/{atotal} 答案 {len(answer)} 字", flush=True)

            res = judge_case(case, answer, tel)
            if case["type"] == "placeholder_honesty":
                res["weather_tool_called"] = "weather" in (tel["tools_called"] or [])
            if case["type"] == "tool":
                res.update({k: res.get(k) for k in
                            ("number_ok", "tool_ok", "extracted_numbers", "last_number")})

            detail = {
                "id": case["id"],
                "type": case["type"],
                "group": case["group"],
                "query": case["query"],
                "answer": answer,
                "retrieved_chunks": tel["chunks"],
                "tools_called": tel["tools_called"],
                "queries": tel.get("queries"),
                "tool_status": tel["tool_status"],
                "anchor_hits": ahit,
                "anchor_total": atotal,
                "anchor_detail": adetail,
                "must_hits": res.get("must_hits"),
                "must_reasons": res.get("must_reasons"),
                "must_hit_count": sum(res["must_hits"]) if res.get("must_hits") else None,
                "must_total": len(case.get("must_contain", [])),
                "should_hits": res.get("should_hits"),
                "should_hit_count": sum(res["should_hits"]) if res.get("should_hits") else None,
                "should_total": len(case.get("should_contain", [])),
                "negative_hits": res.get("negative_hits"),
                "depth_hits": sum(res["should_hits"]) if res.get("should_hits") else None,
                "halluc": res.get("halluc"),
                "hit_rate": res.get("hit_rate"),
                "depth_rate": res.get("depth_rate"),
                "retrieval_hit": tel.get("retrieval_hit"),
                "binary_pass": res.get("pass"),
                "weather_tool_called": res.get("weather_tool_called"),
                "number_ok": res.get("number_ok"),
                "tool_ok": res.get("tool_ok"),
                "extracted_numbers": res.get("extracted_numbers"),
                "last_number": res.get("last_number"),
                "raw_judge_output": res.get("raw_judge_output"),
                "judge_error": res.get("judge_error"),
                "agent_error": tel.get("error"),
                "elapsed": tel.get("elapsed"),
                "iter_count": tel.get("iter_count"),
                "reflection_count": tel.get("reflection_count"),
                "last_action": tel.get("last_action"),
                "repeat": r + 1,
            }
            detail.update(score_case(case, res, tel))
            results.append(detail)
            print(f"     判分：hit_rate={detail['hit_rate']} halluc={detail['halluc']} "
                  f"score={detail['score']} pass={detail['binary_pass']}", flush=True)

    return results


def _unique_path(path):
    """快照永不覆盖 —— 同名存在就加 -2 / -3 后缀。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 2
    while True:
        cand = path.with_name(f"{stem}-{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def print_report(details, cases_by_id, summary, by_repeat=None, across=None, consensus=None):
    print("\n" + "=" * 78)
    print("线 A 答案质量评估报告")
    print("=" * 78)

    if by_repeat and len(by_repeat) > 1:
        _print_repeat_view(by_repeat, across, consensus)
    else:
        _print_single_view(details, cases_by_id, summary)

    print("=" * 78)


def _print_single_view(details, cases_by_id, summary):
    """单遍视图：逐题 + 汇总。"""
    print(f"{'题':<5}{'组':<4}{'hit_rate':<12}{'halluc':<8}{'retr':<7}{'depth':<9}{'score':<8}")
    for d in details:
        c = cases_by_id[d["id"]]
        hit = (f"{d['must_hit_count']}/{d['must_total']}"
               if d.get("must_hit_count") is not None else "—")
        depth = (f"{d['should_hit_count']}/{d['should_total']}"
                 if d.get("should_hit_count") is not None else "—")
        retr = d.get("retrieval_hit")
        print(f"{d['id']:<5}{c['group']:<4}{hit:<12}{str(d.get('halluc')):<8}"
              f"{str(retr):<7}{depth:<9}{str(d.get('score')):<8}")
    print("-" * 78)
    print(f"总分（A/B 组 {summary['scored_questions']} 题均值）= {summary['total_score']}")
    print(f"全局 hit_rate = {summary['hit_rate']}（{summary['must_hits']}/{summary['must_total']} 条）")
    print(f"全局 depth_rate = {summary['depth_rate']}（{summary['depth_hits']}/{summary['depth_total']} 条，不进总分）")
    print(f"幻觉题数 = {summary['halluc_count']} {summary['halluc_cases'] or ''}")
    print(f"检索命中率 = {summary['retrieval_hit_rate']}")
    for key, label in (("honesty_pass", "诚实性通过"),
                       ("placeholder_marker_retention", "占位标记保留"),
                       ("tool_answer_correct", "工具答案正确")):
        if key in summary:
            print(f"{label} = {summary[key]}")
    if "weather_tool_called" in summary:
        print(f"C02 是否调用了 weather 工具 = {summary['weather_tool_called']}")


def _print_repeat_view(by_repeat, across, consensus):
    """多遍视图：逐题共识 + 单次分布 + 跨遍统计。"""
    print(f"\n【逐题共识】（{across.get('repeats', len(by_repeat))} 遍独立评测；一致 = 众数）")
    print(f"{'题':<6}{'各遍命中':<18}{'共识':<10}{'各遍 score':<26}{'共识':<8}{'幻觉':<8}{'检索':<8}")
    for qid, row in (consensus or {}).items():
        hits = "/".join(str(h) for h in row["must_hit_counts"]) or "—"
        tot = row.get("must_total")
        cons = (f"{row['consensus_hits']}/{tot}" if "consensus_hits" in row else "—")
        if row.get("tie"):
            cons += "⚠"
        scores = "/".join(f"{s:.3f}" for s in row["scores"]) or "—"
        cscore = f"{row['consensus_score']:.3f}" if "consensus_score" in row else "—"
        if row.get("score_tie"):
            cscore += "⚠"
        hal = "/".join(str(h) for h in row["halluc"])
        ret = "/".join("" if r is None else str(r) for r in row["retrieval_hit"])
        print(f"{qid:<6}{hits:<18}{cons:<10}{scores:<26}{cscore:<8}{hal:<8}{ret:<8}")

    print(f"\n【单次分布】每一遍 = 一次独立评测")
    print(f"{'遍':<5}{'总分':<9}{'hit_rate':<11}{'depth':<10}{'幻觉':<7}{'检索':<8}{'C01':<6}{'C02':<6}{'D01':<6}{'D02':<6}")
    for s in by_repeat:
        c01 = (s.get("honesty_pass") or {}).get("C01")
        c02 = (s.get("placeholder_marker_retention") or {}).get("C02")
        d01 = (s.get("tool_answer_correct") or {}).get("D01")
        d02 = (s.get("tool_answer_correct") or {}).get("D02")

        def _b(v):
            return {True: "✅", False: "❌", None: "—"}.get(v, "—")

        print(f"{s['repeat']:<5}{str(s.get('total_score')):<9}{str(s.get('hit_rate')):<11}"
              f"{str(s.get('depth_rate')):<10}{str(s.get('halluc_count')):<7}"
              f"{str(s.get('retrieval_hit_rate')):<8}"
              f"{_b(c01):<6}{_b(c02):<6}{_b(d01):<6}{_b(d02):<6}")

    print(f"\n【跨遍统计】")
    for key, label in (("total_score", "总分"),
                       ("hit_rate", "全局 hit_rate"),
                       ("depth_rate", "全局 depth_rate（不进总分）"),
                       ("retrieval_hit_rate", "检索命中率")):
        st = across.get(key)
        if not st:
            continue
        print(f"{label:<28} 均值 {st['mean']}  最小 {st['min']}  最大 {st['max']}  极差 {st['spread']}")
    print(f"{'幻觉题':<28} 逐遍 = {across.get('halluc_per_repeat')}")
    for label in ("honesty", "placeholder", "tool"):
        per_id = across.get(label + "_by_repeat")
        if not per_id:
            continue
        for sid, v in per_id.items():
            print(f"{sid} 通过遍数 = {v['pass_repeats']}/{v['total_repeats']}  逐遍 = {v['values']}"
                  f"  众数 = {v['majority']}")
    print("\n⚠ 单次采样有 LLM 随机性 → 上面的均值是 **本次 3 遍的估计**，不是稳定基线；"
          "极差大 = 该题不稳，别把单遍数字写进简历。")


def main():
    ap = argparse.ArgumentParser(description="线 A 端到端答案质量评测")
    ap.add_argument("--recall-check", action="store_true", help="只跑召回前提检查")
    ap.add_argument("--closed-book", action="store_true", help="闭卷准入探针（裸问模型）")
    ap.add_argument("--repeat", type=int, default=1, help="每题重复遍数（默认 1）")
    ap.add_argument("--only", default="", help="只跑指定题，逗号分隔，如 A01,B02")
    args = ap.parse_args()

    cases, meta = load_cases(CASE_FILE)
    cases_by_id = {c["id"]: c for c in cases}
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    if args.recall_check:
        return mode_recall_check([c for c in cases if not only or c["id"] in only])

    if args.closed_book:
        return mode_closed_book([c for c in cases if not only or c["id"] in only])

    details = mode_full(cases, repeat=args.repeat, only=only)
    if not details:
        print("没有可跑的题")
        return 1

    # 汇总本身不该弄丢原始数据 —— 汇总出错也要把明细落盘
    try:
        summary = summarize(details, cases_by_id)
    except Exception as e:
        print(f"⚠️ 汇总出错（{type(e).__name__}: {e}）—— 原始明细仍会落盘")
        summary = {"summary_error": f"{type(e).__name__}: {e}"}
    try:
        by_repeat = summarize_by_repeat(details, cases_by_id)
        across = summarize_across_repeats(by_repeat)
        consensus = question_consensus(details, cases_by_id)
    except Exception as e:
        print(f"⚠️ 跨遍聚合出错（{type(e).__name__}: {e}）—— 明细仍在快照里")
        by_repeat, across, consensus = [], {}, {}
    try:
        print_report(details, cases_by_id, summary, by_repeat, across, consensus)
    except Exception as e:
        print(f"⚠️ 报告渲染出错（{type(e).__name__}: {e}）—— 明细仍在快照里")

    snapshot = {
        "meta": {
            "created_at": now_iso(),
            "date": today(),
            "corpus_sha256": corpus_sha256(),
            "git_commit": git_commit(),
            "rubric_version": meta.get("rubric_version"),
            "executor_model": EXECUTOR_MODEL,
            "judge_model": JUDGE_MODEL,
            "cases_hash": file_sha256(CASE_FILE),
            "repeat": args.repeat,
        },
        "summary": summary,
        "by_repeat": by_repeat,
        "across_repeats": across,
        "question_consensus": consensus,
        "details": details,
    }
    path = _unique_path(RESULT_DIR / f"answer_quality_{today()}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n快照：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

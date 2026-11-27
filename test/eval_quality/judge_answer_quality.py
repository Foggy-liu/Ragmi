"""test/eval_quality/judge_answer_quality.py —— 线 A 的判分器。

判什么
------
给一道题 + 一段答案，判出三样东西：
- **必答命题**（must_contain）逐条命中与否 → `hit_rate`（总分 0.6 权重，分母是 24 条）
- **深度命题**（should_contain）逐条命中与否 → `depth_rate`（**不进总分**，单独报，分母 6 条）
- **负例命题**（must_not_contain）命中与否 → `halluc`（总分 0.3 权重，**硬闸门**：命中任一条 → 该题封顶 0.5）

C 组（诚实性 / 占位标记）判二值，D 组（calculator）**零 LLM**，用数字抽取比对。

三条防偏规则（设计稿 §2.2）
--------------------------
1. **盲评**：只给「问题 + 答案 + 答案键」。不给检索素材、不给答案出自哪个模型、
   不告诉判分器答案键分几层（设计稿 §6.1.1）。
2. **确定性锚点先行**：`--selftest` 用每题的 `reference_answers[0]` 自检 ——
   判分器必须给满分（hit_rate=1 且 halluc=0），否则判分器不合格、全量不许开始。
3. **盲区必须显式**：判幻觉只能判答案键里显式列出的负例。判分器自己"觉得不对"
   不算幻觉 —— 所以 rubric 里明确写了"负例清单里没有的内容，即使你觉得不对也不算命中"。

为什么不用 `with_structured_output`
-----------------------------------
【实测 2026-11-27】MiniMax M2.5 在 `with_structured_output` 下**必然失败**：
`ValidationError: Invalid JSON: expected value at line 1 column 1 [type=json_invalid]`
—— M2.5 先吐 `<think>...</think>` 再吐 JSON，而 `ThinkingStripRunnable.with_structured_output`
（`agent/llm_wrapper.py:103`）剥 think 剥得太晚：Pydantic 解析发生在 `ChatOpenAI` 内部，
wrapper 的剥离在它之后才跑。（M3.1-Flash 走 tool-calling 路径，所以 `reflect_node` 没事。）

→ 判分器改成：**普通 `.invoke()` → `strip_thinking()` → 自己抽 JSON**。
实测剥完是干净的 `{"items":[{"index":1,"hit":true}]}`。

复算信息
--------
- 判分器模型：MiniMax-M2.5（跨版本隔离 —— 执行体是 M3.1-Flash）
- rubric 版本：见 case 文件的 `rubric_version`
- 快照：见 `run_answer_quality_eval.py`
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 仓库根 = eval_quality/ → test/ → <repo>
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from agent.llm_wrapper import strip_thinking
from utils.models.model_setting import LLMmodel

CASE_FILE = Path(__file__).resolve().parent / "data" / "answer_quality_cases.json"

JUDGE_MODEL = "MiniMax-M2.5"
JUDGE_TIMEOUT = 180
# M2.5 会烧大量 reasoning token（实测单次 reasoning 6618 / output 7020），
# 默认的 max_tokens=4096 会把 JSON 截断掉 → 必须显式加大。
JUDGE_MAX_TOKENS = 16384

SYSTEM = (
    "你是答案质量判分器。你只做一件事：判断给定的待判答案有没有表达出给定的每一条命题。"
    "你不改写答案、不评价文风、不补充知识、不输出任何解释性文字。"
)

RUBRIC = """【问题】
{query}

【待判答案】
{answer}

【必答命题】逐条独立判断答案有没有表达到
{must_block}

【深度命题】题面没有问这些，答到了算加分
{should_block}

【负例命题】答案表达了其中任何一条的含义 = 幻觉
{negative_block}

【判定规则】
1. 语义等价即命中。换了说法、加了限定语、用同义词、把「chunk_size = 300」写成「片段最大 300 字符」都算命中。
2. 命题要求的信息答案里没有 = 不命中。答案提到了相关话题但没说这个事实 = 不命中。
3. 答案里比命题说得多，不影响命中判定；命题没要求的内容不扣分。
4. 负例：答案肯定了那个错误说法（哪怕换措辞）= 命中；答案否定了它、或压根没提 = 不命中。
5. 只判上面列出来的命题。负例清单里没有的内容，即使你觉得不对，也不算命中（不要把"判分器自己觉得不对"当成幻觉）。
6. 每条都要给出理由，理由不超过 15 个字。

【输出】只输出一个 JSON 对象，不要解释文字，不要代码块围栏：
{{"must": [{{"index": 1, "hit": true, "reason": "≤15字"}}], "should": [], "negative": []}}"""

BINARY_RUBRIC = """【问题】
{query}

【待判答案】
{answer}

【预期行为】
{expect}

【判定规则】
1. 待判答案表达了预期行为 = pass；没表达 = fail。
2. 只看答案里有没有表达出预期行为，不评价文风、不补充别的要求。
3. 只输出一个 JSON 对象，不要解释文字，不要代码块围栏：
{{"pass": true, "reason": "≤20字"}}"""


# --------------------------------------------------------------------------
# LLM 判分
# --------------------------------------------------------------------------
_judge_llm = None


def _llm():
    global _judge_llm
    if _judge_llm is None:
        _judge_llm = LLMmodel.create_minimax(
            JUDGE_MODEL,
            temperature=0,
            max_tokens=JUDGE_MAX_TOKENS,
            timeout=JUDGE_TIMEOUT,
        ).chat
    return _judge_llm


def _extract_json(text):
    """从模型输出里抠出 JSON 对象（先剥 think 块，再取第一个 { 到最后一个 }）。"""
    t = strip_thinking(text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError(f"输出里没有 JSON 对象：{t[:150]!r}")
    return json.loads(t[i:j + 1])


def _call_judge(prompt, retry=1):
    """调判分器，返回 (解析后的 dict, 原始文本)。解析失败重试一次。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    last_err = None
    for _ in range(retry + 1):
        try:
            resp = _llm().invoke(
                [SystemMessage(content=SYSTEM), HumanMessage(content=prompt)]
            )
            return _extract_json(resp.content), resp.content
        except Exception as e:  # 网络 / 解析 / 模型异常都归到这里
            last_err = e
            prompt = (
                prompt
                + "\n\n【重试提示】上一次输出无法被解析为 JSON。"
                + "请只输出一个 JSON 对象，不要任何其他文字，不要代码块围栏。"
            )
    raise RuntimeError(f"判分器调用失败：{type(last_err).__name__}: {last_err}")


def _align(items, n):
    """把判分器返回的 [{index, hit, reason}] 对齐成 n 个布尔值（index 从 1 开始）。"""
    hits = [False] * n
    reasons = [""] * n
    for it in items or []:
        try:
            idx = int(it.get("index"))
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= n:
            hits[idx - 1] = bool(it.get("hit"))
            reasons[idx - 1] = str(it.get("reason", ""))[:60]
    return hits, reasons


def _block(lines, empty_hint):
    if not lines:
        return f"（无）{empty_hint}"
    return "\n".join(f"{i}. {t}" for i, t in enumerate(lines, 1))


# --------------------------------------------------------------------------
# 三组分别怎么判
# --------------------------------------------------------------------------
def _judge_ab(case, answer):
    """A/B 组（fact / mechanism）：语义判 must / should / negative。"""
    must = case.get("must_contain", [])
    should = case.get("should_contain", [])
    neg = case.get("must_not_contain", [])

    prompt = RUBRIC.format(
        query=case["query"],
        answer=answer,
        must_block=_block(must, "（本题没有必答命题）"),
        should_block=_block(should, "（本题没有深度命题）"),
        negative_block=_block(neg, "（本题没有负例命题）"),
    )
    data, raw = _call_judge(prompt)

    must_hits, must_reasons = _align(data.get("must"), len(must))
    should_hits, _ = _align(data.get("should"), len(should))
    neg_hits, neg_reasons = _align(data.get("negative"), len(neg))

    halluc = 1 if any(neg_hits) else 0
    return {
        "must_hits": must_hits,
        "must_reasons": must_reasons,
        "should_hits": should_hits,
        "negative_hits": neg_hits,
        "negative_reasons": neg_reasons,
        "hit_rate": (sum(must_hits) / len(must)) if must else None,
        "depth_rate": (sum(should_hits) / len(should)) if should else None,
        "halluc": halluc,
        "raw_judge_output": raw,
        "judge_error": None,
    }


def _judge_c(case, answer):
    """C 组（honesty / placeholder_honesty）：二值。"""
    prompt = BINARY_RUBRIC.format(
        query=case["query"],
        answer=answer,
        expect=case["expect_behavior"],
    )
    data, raw = _call_judge(prompt)
    passed = bool(data.get("pass"))
    reason = str(data.get("reason", ""))[:60]

    fabricated = False
    if case.get("fabricate_regex"):
        fabricated = bool(re.search(case["fabricate_regex"], answer))
        if fabricated:
            passed = False
            reason = (reason + "｜命中禁编造正则").strip("｜")

    return {
        "pass": passed,
        "reason": reason,
        "fabricated": fabricated,
        "raw_judge_output": raw,
        "judge_error": None,
    }


def _norm_num(tok):
    """数字归一化：去千分位逗号；16.0 → 16；-0 → 0。"""
    t = str(tok).replace(",", "").strip()
    try:
        f = float(t)
    except ValueError:
        return t
    if f == int(f):
        return str(int(f))
    return str(f)


def extract_numbers(text):
    """从答案里抽所有阿拉伯数字（含小数、带千分位逗号）。"""
    return [_norm_num(t) for t in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text or "")]


def _judge_d(case, answer, telemetry):
    """D 组（tool）：零 LLM。数字抽取比对 + 工具是否被调用过。"""
    expected = _norm_num(case["expected_answer"])
    numbers = extract_numbers(answer)
    number_ok = expected in numbers
    tool = case.get("expected_tool")
    tools_called = (telemetry or {}).get("tools_called") or []
    tool_ok = (tool in tools_called) if tool else True
    return {
        "pass": bool(number_ok and tool_ok),
        "number_ok": bool(number_ok),
        "tool_ok": bool(tool_ok),
        "expected_tool": tool,
        "tools_called": tools_called,
        "expected_answer": case["expected_answer"],
        "extracted_numbers": numbers,
        "last_number": numbers[-1] if numbers else None,
        "raw_judge_output": None,
        "judge_error": None,
    }


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def load_cases(case_file=CASE_FILE):
    data = json.loads(Path(case_file).read_text(encoding="utf-8"))
    return data["cases"], data


def judge_case(case, answer, telemetry=None):
    """判一道题。返回统一的 dict（字段随 type 不同而不同）。"""
    t = case.get("type")
    try:
        if t in ("fact", "mechanism"):
            res = _judge_ab(case, answer)
        elif t in ("honesty", "placeholder_honesty"):
            res = _judge_c(case, answer)
        elif t == "tool":
            res = _judge_d(case, answer, telemetry)
        else:
            raise ValueError(f"未知题型：{t}")
    except Exception as e:
        # 判分器故障 ≠ 答案错 → 记 judge_error，由调用方决定怎么算分（不计分母，不记 0）
        res = {
            "hit_rate": None,
            "depth_rate": None,
            "halluc": None,
            "pass": None,
            "raw_judge_output": None,
            "judge_error": f"{type(e).__name__}: {e}",
        }
    res["id"] = case["id"]
    res["type"] = t
    return res


# --------------------------------------------------------------------------
# 判分器自检（设计稿 §2.2 第 2 条）
# --------------------------------------------------------------------------
def selftest(case_file=CASE_FILE):
    """用每题的 reference_answers[0] 自检：判分器必须给满分。

    返回 (是否合格, 明细 list)。不合格 = 有题没拿满 must_contain，或命中了负例。
    """
    cases, _ = load_cases(case_file)
    rows, ok = [], True
    for case in cases:
        if case.get("type") not in ("fact", "mechanism"):
            continue
        ref = (case.get("reference_answers") or [""])[0]
        res = judge_case(case, ref)
        full = res.get("hit_rate") == 1.0 and res.get("halluc") == 0
        if not full:
            ok = False
        rows.append(
            {
                "id": case["id"],
                "hit_rate": res.get("hit_rate"),
                "halluc": res.get("halluc"),
                "depth_rate": res.get("depth_rate"),
                "ok": full,
                "error": res.get("judge_error"),
                "must_reasons": res.get("must_reasons"),
                "negative_reasons": res.get("negative_reasons"),
            }
        )
    return ok, rows


def main():
    ap = argparse.ArgumentParser(description="线 A 判分器")
    ap.add_argument("--selftest", action="store_true", help="用参考答案自检判分器")
    ap.add_argument("--case-file", default=str(CASE_FILE))
    args = ap.parse_args()

    if not args.selftest:
        ap.print_help()
        return 0

    print(f"判分器自检（模型 {JUDGE_MODEL}）…")
    ok, rows = selftest(args.case_file)
    for r in rows:
        mark = "✅" if r["ok"] else "❌"
        print(
            f"  {mark} {r['id']}  hit_rate={r['hit_rate']}  "
            f"halluc={r['halluc']}  depth_rate={r['depth_rate']}"
            + (f"  错误：{r['error']}" if r["error"] else "")
        )
        if not r["ok"] and r.get("must_reasons"):
            for i, reason in enumerate(r["must_reasons"], 1):
                if reason:
                    print(f"       必答 {i}: {reason}")
        if not r["ok"] and r.get("negative_reasons"):
            for i, reason in enumerate(r["negative_reasons"], 1):
                if reason:
                    print(f"       负例 {i}: {reason}")
    if ok:
        print("\n判分器合格 —— 允许跑全量。")
        return 0
    print("\n判分器不合格 —— 全量评测不许开始（设计稿 §2.2 第 2 条）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""test/eval/run_agent_eval.py —— 跑 agent_test_cases.json 评估当前 agent。

判断"是否调用 rag_search"：state.messages 中是否出现 ToolMessage。
准确率 = expected_tool 与实际匹配数 / 总数。

模式：
- 默认（无 --mock）：reflect 用真实 LLM（agent 也用真实 LLM），跑 12 个 case
- --mock：只把 reflect 的 LLM 换成 MockLLM（agent 仍用真实 LLM），
         跳过反思那一步的 LLM 成本。稳定性和路由准确率都报。

输出（2026-11-26 改）：
- 真实 LLM → test/eval/data/agent_eval_results_<YYYY-MM-DD>.json
  同名已存在则加 -2 / -3 后缀 —— **快照永不覆盖**。
  理由：每个快照是"这套系统在某一天的路由决策长什么样"的留档，
  多个快照并列 = 波动区间，比一个孤立的数字诚实。
  同时更新 agent_eval_results.json（latest，供文档引用）。
- --mock → test/eval/data/agent_eval_results_mock.json（gitignore，不进仓）

判定口径（2026-11-26 改）：
- **主口径 = 具体工具名**：expected_tool 是具体工具名（rag_search / calculator /
  weather / web_search）或 "none"（不该调任何工具）。判"实际调用的工具里有没有它"。
- **同时并行报旧二值口径**（rag / chat）：由主口径无损反推
  （expected=rag_search→"rag"，其余→"chat"），保证历史快照（2026-11-18 的
  75.0%）与今天的结果**可直接对比**。
- 为什么不只留二值：二值口径下"该调 calculator 却调了 web_search"会被判对
  （只要没调 rag_search 就算 chat），这类错误根本看不见。

2026-11-18 修复（P0-1 的第一步，见 docs/status/项目现状.md §8 P0-1）：
原脚本在 v2.2 全面失效，四处坏：
  1. 数据/结果路径写死在脚本同级目录 → 目录整理后 FileNotFoundError
  2. `sys.path` 指向 `test/archive/` → `import agent` 失败
  3. 读 `iterations` → v2.2 字段叫 `iter_count` → 该字段恒为 0
  4. **路由判定用 `tool_called`（= "调了任何工具"）** → 调 calculator/weather 被
     误判成 "rag" → T02/T09 假错。改为直接看 AIMessage.tool_calls 里的工具名。
另外补了每 case 耗时、tool_status 四态分布、reflect 的 next_action 决策 ——
这些是评估"机制是否真的在起作用"的指标。

2026-11-22：从 test/archive/scripts/ 迁到 test/eval/ —— 它是**唯一活着的**离线
评估脚本（archive/ 里的都是过时的、且只留本地不上传）。路径改为相对脚本目录。
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 仓库根 = eval/ → test/ → <repo>
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 强制 UTF-8 输出（Windows GBK 默认编码会炸 ✓/✗）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain_core.messages import AIMessage, HumanMessage

from agent.constants import TOTAL_TIMEOUT
from agent.graph import build_graph
from agent.runtime import RECURSION_LIMIT, _extract_answer


class MockLLM:
    """用于 --mock 模式的假 LLM（只替换 reflect 节点的 LLM）。

    agent 节点的 LLM 不替换（仍用真实 LLM 决策 + 调 rag_search 工具）。
    所以 --mock 模式下：
    - graph 走完完整流程（stability 可信）
    - 跳过 reflect 的 LLM 调用（省成本）
    - routing accuracy 仍可观察（来自真实 agent LLM 的决策）

    注意：这个 mock 只让 reflect 不调 LLM，不让 agent 不调 LLM。

    ★ v2.2 的 reflect 节点用 `with_structured_output(ReflectOutput)`，
      解析出的对象要有 `.next_action` / `.critique` —— 所以 mock 不能返回
      普通 AIMessage，要返回 ReflectOutput 实例。
    """

    def __init__(self):
        self.invoke_calls = []

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        from agent.nodes.reflect_node import ReflectOutput

        return ReflectOutput(next_action="end", critique="[MOCK] 固定判 end")


def evaluate_one(graph, query: str) -> dict:
    """跑一次 agent，返回完整遥测。

    直接 invoke 图（而不是 ask()）是因为 ask() 的 debug 模式只吐 5 个字段，
    **不告诉你是哪个工具被调的** —— 而路由准确率恰恰要看工具名。
    """
    started = time.time()
    try:
        result = graph.invoke(
            {"messages": [HumanMessage(query)], "deadline": time.time() + TOTAL_TIMEOUT},
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except Exception as e:
        return {
            "answer": "",
            "actual_tools": [],
            "tool_status": {},
            "iter_count": 0,
            "reflection_count": 0,
            "next_action": "error",
            "elapsed": time.time() - started,
            "error": f"{type(e).__name__}: {e}",
        }

    msgs = result.get("messages", [])

    # 实际调了哪些工具（按调用顺序，保留重复 —— 并发同调两次是真实行为）
    actual_tools = []
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                actual_tools.append(tc.get("name"))

    # 工具状态四态：{call_id: {tool, status, code, retryable}}
    tool_status = result.get("tool_status", {}) or {}
    statuses = [v.get("status") for v in tool_status.values()]

    return {
        "answer": _extract_answer(msgs),
        "actual_tools": actual_tools,
        "tool_status": statuses,
        "iter_count": result.get("iter_count", 0),
        "reflection_count": result.get("reflection_count", 0),
        "next_action": result.get("next_action", "end"),
        "elapsed": time.time() - started,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="用 MockLLM 替代真实 LLM（只测 stability）")
    args = parser.parse_args()
    use_mock = args.mock

    if use_mock:
        # v2.2 的 reflect 节点没有模块级 `_llm`，而是 `_get_llm()` 懒加载 →
        # 替换 `_get_llm` 本身（模块已改名 reflect → reflect_node）。
        from agent.nodes import reflect_node as reflect_mod

        reflect_mod._get_llm = lambda: MockLLM()
        print("=== --mock 模式：reflect 用 MockLLM（跳过反思 LLM 成本），agent 仍用真实 LLM ===\n")

    data_dir = Path(__file__).resolve().parent / "data"
    cases_path = data_dir / "agent_test_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    print(f"加载 {len(cases)} 个测试 case\n")
    print(f"{'ID':<5}{'期望':<7}{'实际工具':<22}{'对/错':<6}{'动作':<11}{'秒':>6}  query")
    print("-" * 96)

    graph = build_graph()
    details = []

    # 口径自检：expected_tool 应该是具体工具名或 "none"，
    # 而不是旧的二值 "chat"/"rag"。发现旧值直接报错 —— 静默跑出一个
    # 混着两套口径的数字，比报错难查得多。
    _BINARY_VALUES = {"chat", "rag"}
    _legacy = [c["id"] for c in cases if c["expected_tool"] in _BINARY_VALUES]
    if _legacy:
        raise SystemExit(
            f"agent_test_cases.json 里这些 case 还用旧的二值口径 {sorted(_legacy)}："
            f"{sorted(_BINARY_VALUES)}\n"
            f"请改成具体工具名（rag_search / calculator / weather / web_search / none）。"
        )

    for case in cases:
        case_id = case["id"]
        query = case["query"]
        expected = case["expected_tool"]

        t = evaluate_one(graph, query)
        tools = t["actual_tools"]
        used_rag = "rag_search" in tools

        # ★ 主口径（2026-11-26）：按**具体工具名**判对错。
        #   expected="none"       → 不该调任何工具，实际没调才算对
        #   expected="calculator" → 实际调了 calculator 才算对
        #   （旧二值口径会把"该调 calculator 却调了 web_search"判成对）
        #
        # ★ 旧二值口径并行计算，保证与历史快照（2026-11-18 的 75.0%）可直接对比：
        #   期望 rag_search → "rag"；其余（含 none / calculator / weather）→ "chat"
        #   实际：调了 rag_search → "rag"；否则 "chat"
        if t["error"] is not None:
            actual = "error"
            is_correct = False
            status = "exception"
            mark = "✗"
        else:
            actual = "none" if not tools else tools[0]
            is_correct = (actual == expected)
            status = "correct" if is_correct else "wrong_tool"
            mark = "✓" if is_correct else "✗"

        binary_expected = "rag" if expected == "rag_search" else "chat"
        binary_actual = "rag" if used_rag else "chat"
        binary_correct = (binary_actual == binary_expected)

        tool_desc = ",".join(tools) if tools else "(无)"
        print(
            f"{case_id:<5}{expected:<12}{tool_desc[:20]:<22}{mark:<6}"
            f"{t['next_action']:<11}{t['elapsed']:>6.1f}  {query[:30]}"
        )

        detail = {
            "id": case_id,
            "query": query,
            "expected": expected,
            "actual": actual,
            "actual_tools": tools,
            "correct": is_correct,
            "correct_binary_rubric": binary_correct,
            "status": status,
            "response_preview": (t["answer"] or "")[:80] + ("..." if len(t["answer"] or "") > 80 else ""),
            "iter_count": t["iter_count"],
            "reflection_count": t["reflection_count"],
            "next_action": t["next_action"],
            "tool_status": t["tool_status"],
            "elapsed_sec": round(t["elapsed"], 2),
        }
        if t["error"] is not None:
            detail["error"] = t["error"]
        details.append(detail)

    total = len(cases)
    exceptions = sum(1 for d in details if d["status"] == "exception")
    wrong_tool = sum(1 for d in details if d["status"] == "wrong_tool")
    correct = sum(1 for d in details if d["status"] == "correct")
    stability = (total - exceptions) / total * 100 if total else 0
    evaluated = total - exceptions
    routing_accuracy = correct / evaluated * 100 if evaluated else 0

    # ★ 旧二值口径（rag / chat）并行统计 —— 与历史快照直接可比。
    #   期望：rag_search → "rag"；其余（none / calculator / weather / web_search）→ "chat"
    #   实际：调了 rag_search → "rag"；否则 → "chat"
    binary_correct = sum(1 for d in details if d["correct_binary_rubric"])
    binary_accuracy = binary_correct / evaluated * 100 if evaluated else 0
    # 两个口径判出来不同的 case —— 这正是二值口径"看不见的错误"清单
    rubric_diff = [
        {"id": d["id"], "expected": d["expected"], "actual_tools": d["actual_tools"]}
        for d in details
        if d["correct"] != d["correct_binary_rubric"]
    ]

    # 机制维度统计 —— 用来回答"反思/工具机制到底有没有在起作用"
    #
    # ⚠️ `next_action` 是**最后一次**反思的决策 —— reflect 节点每次运行都会覆盖它。
    #    所以"最终动作全是 end"**不等于**"反思没工作过"：
    #    `reflection_count > 1` 说明 reflect 跑了多轮，
    #    第一轮一定判了 rewrite / re_iterate（否则图不会再回到 reflect）。
    #    两个都要看。
    final_actions = {}
    refl_counts = {}
    for d in details:
        final_actions[d["next_action"]] = final_actions.get(d["next_action"], 0) + 1
        k = d["reflection_count"]
        refl_counts[k] = refl_counts.get(k, 0) + 1
    status_counter = {}
    for d in details:
        for s in d["tool_status"]:
            status_counter[s] = status_counter.get(s, 0) + 1
    elapsed_list = sorted(d["elapsed_sec"] for d in details)
    median = elapsed_list[len(elapsed_list) // 2] if elapsed_list else 0

    print("-" * 96)
    print(f"\n总准确率(主口径·具体工具名): {correct}/{total} = {correct/total*100 if total else 0:.1f}%")
    print(f"  - Tool Routing Accuracy: {correct}/{total - exceptions} = {routing_accuracy:.1f}%")
    print(f"  - Agent Stability: {total-exceptions}/{total} = {stability:.1f}%")
    print(f"  - Exceptions: {exceptions}, Wrong Tool: {wrong_tool}")
    print(f"  - [旧二值口径 rag/chat, 供与历史快照对比]: {binary_correct}/{total - exceptions} = {binary_accuracy:.1f}%")
    print(f"  - 两口径判定不一致的 case: {len(rubric_diff)} 个"
          + (f" -> {[r['id'] for r in rubric_diff]}" if rubric_diff else ""))
    print(f"  - reflect 最终决策分布: {final_actions}")
    print(f"  - reflect 轮数分布 (reflection_count): {refl_counts}")
    print(f"  - 工具状态四态分布: {status_counter}")
    print(f"  - 工具调用总数: {sum(status_counter.values())}")
    print(f"  - 耗时: 最小 {elapsed_list[0]:.1f}s / 中位 {median:.1f}s / 最大 {elapsed_list[-1]:.1f}s")
    if use_mock:
        print("  - (--mock 模式: reflect 用 MockLLM，agent 用真实 LLM)")

    # 保存详细结果
    # ★ --mock 写**另一个文件** —— mock 结果不能覆盖真实 LLM 的快照。
    #   （2026-11-22 实测踩过：跑一次 --mock 把 75.0% 的真实快照冲成了 91.67%）
    #
    # ★ 真实模式按日期留档，同名已存在就加 -2/-3 后缀 —— **快照永不覆盖**。
    #   每个快照是"这套系统在某一天的路由决策"的留档，
    #   多个快照并列 = 波动区间，比一个孤立的数字诚实。
    #   同时更新 agent_eval_results.json 作为 latest（供文档引用）。
    if use_mock:
        out_path = data_dir / "agent_eval_results_mock.json"
    else:
        stamp = time.strftime("%Y-%m-%d")
        out_path = data_dir / f"agent_eval_results_{stamp}.json"
        n = 1
        while out_path.exists():
            n += 1
            out_path = data_dir / f"agent_eval_results_{stamp}-{n}.json"

    payload = {
        "summary": {
            "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rubric": "tool_name",
            "rubric_note": "主口径按具体工具名判对错；同时并行报旧二值口径 rag/chat，与历史快照可比",
            "total": total,
            "correct": correct,
            "routing_accuracy": routing_accuracy,
            "routing_accuracy_binary_rubric": binary_accuracy,
            "correct_binary_rubric": binary_correct,
            "rubric_disagreements": rubric_diff,
            "stability": stability,
            "exceptions": exceptions,
            "wrong_tool": wrong_tool,
            "reflect_final_action": final_actions,
            "reflection_count_distribution": refl_counts,
            "tool_status_distribution": status_counter,
            "tool_calls_total": sum(status_counter.values()),
            "elapsed_median_sec": median,
            "mode": "mock" if use_mock else "real",
            "note": "--mock 仅替换 reflect._llm，agent 仍用真实 LLM" if use_mock else None,
        },
        "details": details,
    }

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细结果已保存: {out_path}")

    # 真实模式额外更新 latest（agent_eval_results.json），供文档引用。
    # ★ 日期快照才是历史留档；latest 只是"当前值"，被覆盖没关系。
    if not use_mock:
        latest = data_dir / "agent_eval_results.json"
        latest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"latest 已更新: {latest}")


if __name__ == "__main__":
    main()
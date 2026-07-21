"""test/run_agent_eval.py —— 跑 agent_test_cases.json 评估当前 agent。

判断"是否调用 rag_search"：state.messages 中是否出现 ToolMessage。
准确率 = expected_tool 与实际匹配数 / 总数。

模式：
- 默认（无 --mock）：reflect 用真实 LLM（agent 也用真实 LLM），跑 12 个 case
- --mock：只把 reflect 的 LLM 换成 MockLLM（agent 仍用真实 LLM），
         跳过反思那一步的 LLM 成本。稳定性和路由准确率都报。

输出：test/agent_eval_results.json（summary + details）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 强制 UTF-8 输出（Windows GBK 默认编码会炸 ✓/✗）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from agent.graph import build_graph


class MockLLM:
    """用于 --mock 模式的假 LLM（只替换 reflect 节点的 LLM）。

    agent 节点的 LLM 不替换（仍用真实 LLM 决策 + 调 rag_search 工具）。
    所以 --mock 模式下：
    - graph 走完完整流程（stability 可信）
    - 跳过 reflect 的 LLM 调用（省成本）
    - routing accuracy 仍可观察（来自真实 agent LLM 的决策）

    注意：这个 mock 只让 reflect 不调 LLM，不让 agent 不调 LLM。
    """

    def __init__(self):
        self.invoke_calls = []

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        from langchain_core.messages import AIMessage
        return AIMessage(content="[MOCK] 这是 mock LLM 的回答。")


def evaluate_one(graph, query: str, use_mock: bool) -> tuple:
    """跑一次 agent，返回 (answer, tool_called, iterations, reflection_count, error)。

    tool_called=True 表示 routing 选了 rag tool（state.messages 含 ToolMessage）。
    use_mock=True 时 tool_called 恒为 False（mock LLM 不调工具）。
    error 仅在抛异常时为 str，否则为 None。
    """
    from agent.runtime import ask

    try:
        debug_result = ask(query, debug=True)
    except Exception as e:
        return "", False, 0, 0, str(e)

    if isinstance(debug_result, str):
        return debug_result, False, 0, 0, "ask() returned str instead of dict"

    return (
        debug_result.get("answer", ""),
        bool(debug_result.get("tool_called")),
        debug_result.get("iterations", 0),
        debug_result.get("reflection_count", 0),
        None,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="用 MockLLM 替代真实 LLM（只测 stability）")
    args = parser.parse_args()
    use_mock = args.mock

    if use_mock:
        from agent.nodes import reflect as reflect_mod
        reflect_mod._llm = MockLLM()
        print("=== --mock 模式：reflect 用 MockLLM（跳过反思 LLM 成本），agent 仍用真实 LLM ===\n")

    cases_path = Path(__file__).parent / "agent_test_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    print(f"加载 {len(cases)} 个测试 case\n")
    print(f"{'ID':<5}{'期望':<8}{'实际':<8}{'对/错':<6}query")
    print("-" * 80)

    graph = build_graph()
    details = []

    for case in cases:
        case_id = case["id"]
        query = case["query"]
        expected = case["expected_tool"]

        answer, tool_called, iterations, reflection_count, error = evaluate_one(graph, query, use_mock)
        actual = "rag" if tool_called else "chat"

        if error is not None:
            status = "exception"
            actual = "error"
            is_correct = False
            mark = "✗"
        else:
            is_correct = (actual == expected)
            status = "correct" if is_correct else "wrong_tool"
            mark = "✓" if is_correct else "✗"

        print(f"{case_id:<5}{expected:<8}{actual:<8}{mark:<6}{query[:40]}")

        detail = {
            "id": case_id,
            "query": query,
            "expected": expected,
            "actual": actual,
            "correct": is_correct,
            "status": status,
            "response_preview": (answer or "")[:80] + ("..." if len(answer or "") > 80 else ""),
            "iterations": iterations,
            "reflection_count": reflection_count,
        }
        if error is not None:
            detail["error"] = error
        details.append(detail)

    total = len(cases)
    exceptions = sum(1 for d in details if d["status"] == "exception")
    wrong_tool = sum(1 for d in details if d["status"] == "wrong_tool")
    correct = sum(1 for d in details if d["status"] == "correct")
    stability = (total - exceptions) / total * 100 if total else 0
    evaluated = total - exceptions
    routing_accuracy = correct / evaluated * 100 if evaluated else 0

    print("-" * 80)
    print(f"\n总准确率: {correct}/{total} = {correct/total*100 if total else 0:.1f}%")
    print(f"  - Tool Routing Accuracy: {correct}/{total - exceptions} = {routing_accuracy:.1f}%")
    print(f"  - Agent Stability: {total-exceptions}/{total} = {stability:.1f}%")
    print(f"  - Exceptions: {exceptions}, Wrong Tool: {wrong_tool}")
    if use_mock:
        print("  - (--mock 模式: reflect 用 MockLLM，agent 用真实 LLM)")

    # 保存详细结果
    out_path = Path(__file__).parent / "agent_eval_results.json"
    out_path.write_text(
        json.dumps({
            "summary": {
                "total": total,
                "correct": correct,
                "routing_accuracy": routing_accuracy,
                "stability": stability,
                "exceptions": exceptions,
                "wrong_tool": wrong_tool,
                "mode": "mock" if use_mock else "real",
                "note": "--mock 仅替换 reflect._llm，agent 仍用真实 LLM" if use_mock else None,
            },
            "details": details,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细结果已保存: {out_path}")


if __name__ == "__main__":
    main()
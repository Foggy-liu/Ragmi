"""test/run_agent_eval.py —— 跑 agent_test_cases.json 评估当前 agent。

判断"是否调用 rag_search"：state.messages 中是否出现 ToolMessage。
准确率 = expected_tool 与实际匹配数 / 总数。
"""

import json
from pathlib import Path

from agent.graph import build_graph


def evaluate_one(graph, query: str) -> tuple[str, bool, int, int]:
    """跑一次 agent，返回 (response, tool_called, iterations, reflection_count)。"""
    # 用 debug 模式拿 metadata
    from agent.runtime import ask

    debug_result = ask(query, debug=True)
    if isinstance(debug_result, str):
        # 异常 fallback (ask 返回 error string)
        return debug_result, False, 0, 0
    return (
        debug_result["answer"],
        debug_result["tool_called"],
        debug_result["iterations"],
        debug_result["reflection_count"],
    )


def main():
    cases_path = Path(__file__).parent / "agent_test_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    print(f"加载 {len(cases)} 个测试 case\n")
    print(f"{'ID':<5}{'期望':<8}{'实际':<8}{'对/错':<6}query")
    print("-" * 80)

    graph = build_graph()
    correct = 0
    rag_correct = 0
    rag_total = 0
    chat_correct = 0
    chat_total = 0
    details = []

    for case in cases:
        case_id = case["id"]
        query = case["query"]
        expected = case["expected_tool"]

        try:
            response, tool_called, iterations, reflection_count = evaluate_one(graph, query)
            actual = "rag" if tool_called else "chat"
            is_correct = (actual == expected)
            mark = "✓" if is_correct else "✗"

            print(f"{case_id:<5}{expected:<8}{actual:<8}{mark:<6}{query[:40]}")

            details.append({
                "id": case_id,
                "query": query,
                "expected": expected,
                "actual": actual,
                "correct": is_correct,
                "response_preview": response[:80] + ("..." if len(response) > 80 else ""),
                "iterations": iterations,
                "reflection_count": reflection_count,
            })

            if is_correct:
                correct += 1
                if expected == "rag":
                    rag_correct += 1
                else:
                    chat_correct += 1

            if expected == "rag":
                rag_total += 1
            else:
                chat_total += 1

        except Exception as e:
            print(f"{case_id:<5}{expected:<8}{'ERROR':<8}{'✗':<6}{query[:40]}  ({e})")
            details.append({
                "id": case_id,
                "query": query,
                "expected": expected,
                "actual": "error",
                "correct": False,
                "error": str(e),
            })

    total = len(cases)
    accuracy = correct / total * 100 if total else 0

    print("-" * 80)
    print(f"\n总准确率: {correct}/{total} = {accuracy:.1f}%")
    print(f"  - RAG 类: {rag_correct}/{rag_total} = {rag_correct/rag_total*100 if rag_total else 0:.1f}%")
    print(f"  - Chat 类: {chat_correct}/{chat_total} = {chat_correct/chat_total*100 if chat_total else 0:.1f}%")

    # 保存详细结果
    out_path = Path(__file__).parent / "agent_eval_results.json"
    out_path.write_text(
        json.dumps({
            "summary": {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "rag_correct": rag_correct,
                "rag_total": rag_total,
                "chat_correct": chat_correct,
                "chat_total": chat_total,
            },
            "details": details,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细结果已保存: {out_path}")


if __name__ == "__main__":
    main()
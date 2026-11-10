"""跑 v1 agent 拿基线数据"""
import json
import requests
import time
from pathlib import Path

V1_URL = "http://localhost:8000/agent/chat"
CASES_PATH = Path(__file__).parent / "agent_test_cases.json"
OUTPUT_PATH = Path(__file__).parent / "v1_baseline_results.json"


def run_v1_case(case: dict) -> dict:
    """跑 1 个 case 记结果"""
    start = time.time()
    try:
        resp = requests.post(
            V1_URL,
            json={"query": case["query"], "session_id": f"v1_baseline_{case['id']}"},
            timeout=180
        )
        elapsed = time.time() - start
        data = resp.json()

        tool_chosen = data.get("tool_used", "unknown").split(" ")[0]  # 处理 "chat (降级)" 这种情况
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": tool_chosen,
            "is_correct": tool_chosen == case["expected_tool"],
            "response_time": round(elapsed, 2),
            "iterations": data.get("iterations", 0),
            "response_preview": data.get("response", "")[:200]
        }
    except Exception as e:
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": "ERROR",
            "is_correct": False,
            "error": str(e),
            "response_time": round(time.time() - start, 2)
        }


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    print(f"Running v1 baseline on {len(cases)} cases...")
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['query'][:30]}...")
        result = run_v1_case(case)
        results.append(result)
        status = "✓" if result["is_correct"] else "✗"
        print(f"  {status} chose {result['tool_chosen']} (expected {case['expected_tool']}) in {result['response_time']}s")

    # 统计
    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    avg_time = sum(r["response_time"] for r in results) / total

    summary = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3),
        "avg_response_time": round(avg_time, 2),
        "results": results
    }

    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== v1 Baseline ===")
    print(f"Accuracy: {correct}/{total} = {summary['accuracy']*100}%")
    print(f"Avg response time: {summary['avg_response_time']}s")
    print(f"Results saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

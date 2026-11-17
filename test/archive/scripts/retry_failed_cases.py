"""重跑失败的 case"""
import json
import requests
import time
from pathlib import Path

V1_URL = "http://localhost:8000/agent/chat"
CASES_PATH = Path(__file__).parent / "agent_test_cases.json"
RESULT_PATH = Path(__file__).parent / "v1_baseline_results.json"


def run_case(case):
    start = time.time()
    try:
        resp = requests.post(V1_URL, json={"query": case["query"], "session_id": f"v1_retry_{case['id']}"}, timeout=180)
        elapsed = time.time() - start
        data = resp.json()
        tool = data.get("tool_used", "unknown").split(" ")[0]
        return {
            "id": case["id"],
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "tool_chosen": tool,
            "is_correct": tool == case["expected_tool"],
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
            "error": str(e)[:200],
            "response_time": round(time.time() - start, 2)
        }


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    full_result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    results_by_id = {r["id"]: r for r in full_result["results"]}

    retry_targets = [r["id"] for r in full_result["results"] if r["tool_chosen"] == "ERROR"]
    print(f"重试 {len(retry_targets)} 个失败 case: {retry_targets}")

    for cid in retry_targets:
        case = next(c for c in cases if c["id"] == cid)
        print(f"  {cid}: {case['query'][:30]}...")
        for attempt in range(3):
            new_result = run_case(case)
            if new_result["tool_chosen"] != "ERROR":
                results_by_id[cid] = new_result
                print(f"    attempt {attempt+1} OK: {new_result['tool_chosen']} ({new_result['response_time']}s)")
                break
            else:
                print(f"    attempt {attempt+1} failed, retrying...")
                time.sleep(3)
        else:
            print(f"    3 次都失败，保持原 ERROR 记录")

    # 重算统计
    new_results = list(results_by_id.values())
    correct = sum(1 for r in new_results if r["is_correct"])
    total = len(new_results)
    avg_time = sum(r["response_time"] for r in new_results) / total

    new_summary = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3),
        "avg_response_time": round(avg_time, 2),
        "results": new_results
    }

    RESULT_PATH.write_text(json.dumps(new_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== v1 Baseline (重试后) ===")
    print(f"Accuracy: {correct}/{total} = {new_summary['accuracy']*100}%")
    print(f"Avg: {new_summary['avg_response_time']}s")


if __name__ == "__main__":
    main()

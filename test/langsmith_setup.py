"""test/langsmith_setup.py —— 把 agent_test_cases.json 转成 LangSmith Dataset。

一次性脚本：建 dataset + 上传 12 个 case。后续只跑 evaluate()。

用法：
    python test/langsmith_setup.py
"""
import json
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

# 自动从 worktree 根目录的 .env 加载 LANGSMITH_API_KEY
load_dotenv(Path(__file__).parent.parent / ".env")


def main():
    cases_path = Path(__file__).parent / "agent_test_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    client = Client()
    dataset_name = "ragmi-agent-eval-v2"

    # 已存在则跳过创建, 复用
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        print(f"Dataset '{dataset_name}' 已存在, ID={dataset.id}")
    except Exception:
        dataset = client.create_dataset(dataset_name)
        print(f"创建 Dataset '{dataset_name}', ID={dataset.id}")

    for case in cases:
        client.create_example(
            inputs={"question": case["query"]},
            outputs={
                "expected_tool": case["expected_tool"],
                "reference_keywords": case.get("reference_keywords", []),
            },
            dataset_id=dataset.id,
        )

    print(f"上传 {len(cases)} 个 case 完成")


if __name__ == "__main__":
    main()

"""test/langsmith_eval.py —— 用 LangSmith 跑 evaluate 实验。

用法：
    python test/langsmith_eval.py --prefix v2-with-reflection
    python test/langsmith_eval.py --prefix v2-baseline

实验结果在 LangSmith 仪表盘对比：
https://smith.langchain.com → ragmi-agent-v2 项目
"""
import argparse
import sys
from pathlib import Path

# 把项目根目录加到 sys.path, 确保 `from agent.runtime import ask` 能找到包
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from langsmith import evaluate

from agent.runtime import ask
from test.langsmith_evaluators import (
    answer_keyword_evaluator,
    tool_choice_evaluator,
)

# 自动从 worktree 根目录的 .env 加载 LANGSMITH_API_KEY（参考 langsmith_setup.py）
load_dotenv(Path(__file__).parent.parent / ".env")


def agent_target(inputs: dict) -> dict:
    """LangSmith target 函数：跑一次 agent, 返回 outputs 供 evaluator 打分。

    用 debug=True 拿完整 metadata。
    """
    debug_info = ask(inputs["question"], debug=True)

    # ask 在 debug=False 时返回 str, debug=True 时返回 dict
    if isinstance(debug_info, str):
        return {
            "answer": debug_info,
            "tool_called": False,
            "iterations": 0,
            "reflection_count": 0,
            "score": None,
        }

    return {
        "answer": debug_info["answer"],
        "tool_called": debug_info["tool_called"],
        "iterations": debug_info["iterations"],
        "reflection_count": debug_info["reflection_count"],
        "score": debug_info["score"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prefix",
        default="v2-with-reflection",
        help="experiment_prefix, 决定在 LangSmith 仪表盘上的实验名",
    )
    args = parser.parse_args()

    results = evaluate(
        agent_target,
        data="ragmi-agent-eval-v2",
        evaluators=[tool_choice_evaluator, answer_keyword_evaluator],
        experiment_prefix=args.prefix,
    )

    print(f"\n实验 '{args.prefix}' 已完成")
    print("去 LangSmith 仪表盘查看 trace + 评分:")
    print("  https://smith.langchain.com → ragmi-agent-v2 项目")


if __name__ == "__main__":
    main()
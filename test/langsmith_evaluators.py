"""test/langsmith_evaluators.py —— LangSmith 评估函数。

两个 evaluator：
- tool_choice_evaluator: agent 选对工具没（硬指标）
- answer_keyword_evaluator: 答案含期望关键词没（软指标，仅对有 reference_keywords 的 case）

输入约定（来自 agent_target 的 outputs）：
- answer: 最终答案字符串
- tool_called: 是否调用了工具（来自 debug mode）
- iterations / reflection_count: 元数据

ground truth 来自 example.outputs（来自 dataset）：
- expected_tool: "rag" 或 "chat"
- reference_keywords: list[str], 可选
"""


def tool_choice_evaluator(run, example) -> dict:
    """评 'agent 选对工具没'。

    score: 1 (选对) / 0 (选错)
    """
    expected = example.outputs.get("expected_tool")
    if expected is None:
        return {"key": "tool_choice", "score": None}

    actual = "rag" if run.outputs.get("tool_called", False) else "chat"
    return {
        "key": "tool_choice",
        "score": int(actual == expected),
    }


def answer_keyword_evaluator(run, example) -> dict:
    """评 '答案含期望关键词没'。

    score: 1 (含至少一个关键词) / 0 (都不含) / None (此 case 无关键词, 跳过)
    """
    keywords = example.outputs.get("reference_keywords") or []
    if not keywords:
        return {"key": "answer_keywords", "score": None}

    answer = run.outputs.get("answer", "") or ""
    matched = any(kw in answer for kw in keywords)
    return {
        "key": "answer_keywords",
        "score": int(matched),
    }
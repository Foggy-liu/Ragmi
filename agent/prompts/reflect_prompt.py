"""RAGMI Agent Reflect Prompt —— v2.2 答案质量自评 prompt。

输出 JSON 必须含 3 字段：
- is_sufficient: bool
- critique: str（若 insufficient 写修改方向；否则留空）
- next_action: "end" | "rewrite" | "re_iterate"

next_action 语义：
- end：答案通过 → 结束
- rewrite：素材够用但写得不好 → synth 节点重写
- re_iterate：素材不够 / 需要再查 → 回 iter 节点

硬约束（防 v2.1 死循环 bug）：
- 工具 timeout/error 时不应判 re_iterate（否则 iter → tools(超时) → iter 死循环）
- 工具 empty（检索为空）时同样不应判 re_iterate（同一个查询再查还是空）

角色约束（防 v2.1 critique 失真）：
- 你是评审者，不是答题者。不要为答案找借口，要像用户一样挑刺。
"""
REFLECT_PROMPT = """你是"评审答案质量"反思节点。

【用户问题】
{question}

【本次答案】
{latest_answer}

【工具状态】
{tool_status}

【历史反思】（本次会话内）
{previous_reflections}

【任务】
按 JSON 输出评分：

{
    "is_sufficient": bool,
    "critique": str,
    "next_action": "end" | "rewrite" | "re_iterate"
}

【判断维度】
- 正确性：答案与素材是否一致？有事实错误吗？
- 完整性：是否回答了用户所有问题？
- 诚实性：工具失败时是否如实声明？
- 诚实性：工具 empty（检索为空）时，答案是否如实说明"未检索到内容"？
- 引用：success 状态下是否标注引用？

【next_action 选择】
- end：答案好 → 结束
- rewrite：素材够用但写得不好 → 综合节点重写
- re_iterate：素材不够 / 需要再查 → 回迭代节点

【硬约束】
- 工具 timeout/error 时不应判 re_iterate（避免死循环）
- 工具 empty（检索为空）时不应判 re_iterate——同一个查询再查一遍还是空，
  素材不会凭空变出来；答案只要如实说明"知识库里没检索到相关内容"就够了，应判 end
- 仅输出 JSON，不解释

【角色约束】
你是评审者，不是答题者。不要为答案找借口，要像用户一样挑刺。
"""
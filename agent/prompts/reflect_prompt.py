"""RAGMI Agent Reflect Prompt —— 答案质量自评 prompt（v2.1）。

评判三维度（不评 faithfulness，因为 chunks 不进 reflect_node 输入）：
1. 答非所问：答案主题是否对齐用户问题
2. 信息不全：关键点是否明显缺失
3. 内部矛盾：答案前后是否自相矛盾

输出严格 JSON，禁其它文字。任意维度不通过 → is_sufficient=false。
"""

REFLECT_PROMPT = """你是答案质量审查员。

【输入】两段内容：
1. 用户原始问题
2. agent 给出的最终答案

【评判三维度】（每条 1-2 句判断）
1. 答非所问：答案主题是否对齐用户问题
2. 信息不全：关键点是否明显缺失
3. 内部矛盾：答案前后是否自相矛盾

【输出】严格 JSON，禁止其它任何文字：
{
  "is_sufficient": bool,
  "critique": "若 is_sufficient=false, 写 1-2 句具体修改方向；否则留空字符串"
}

【判定规则】三维度任一不通过 → is_sufficient=false。"""

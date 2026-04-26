# Agent 结构化输出实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Agent 的工具选择从正则解析改为结构化 JSON 输出，提高工具选择的可靠性

**Architecture:** 修改 LLM 提示词要求输出 JSON 格式，同时保留正则解析作为 fallback，确保兼容性

**Tech Stack:** Python, FastAPI, LLM (支持 JSON 输出)

---

## 文件结构

```
agent/
├── react_prompt.py              # 修改提示词，要求 JSON 输出
├── controller.py                 # 适配新的解析结果
├── core/
│   └── reasoning.py             # parse_tool_choice() 改为 JSON 解析
```

---

## Task 1: 修改 react_prompt.py - JSON 输出提示词

**Files:**
- Modify: `agent/react_prompt.py:1-113`
- Test: `agent/core/test_reasoning.py` (新建)

- [ ] **Step 1: 备份当前提示词，创建新版本**

将当前的提示词保存为 `REACT_SYSTEM_PROMPT_OLD`，新增 `REACT_SYSTEM_PROMPT` 使用 JSON 输出格式

```python
# 在文件末尾添加
REACT_SYSTEM_PROMPT_LITE = """你是智能决策助手，需要根据用户问题选择合适的工具。

【可用工具】
- rag: 知识库问答（查询具体事实、数据、文档内容时使用）
- chat: 普通对话（日常聊天、创作、计算、推理时使用）

【输出格式】
请以 JSON 格式输出你的决策，不要包含其他内容：

{
  "tool": "rag 或 chat",
  "confidence": 0.0-1.0 之间的置信度,
  "reasoning": "简短的推理过程"
}

示例：
- 用户问题："劳动法年假规定是什么？"
输出：{"tool": "rag", "confidence": 0.9, "reasoning": "询问法律条文，需要检索知识库"}

- 用户问题："你好，今天天气怎么样？"
输出：{"tool": "chat", "confidence": 0.95, "reasoning": "日常聊天，无需检索"}

请以 JSON 格式回应用户："""
```

- [ ] **Step 2: 验证提示词格式**

```python
import json
test_json = '{"tool": "rag", "confidence": 0.9, "reasoning": "测试"}'
result = json.loads(test_json)
assert result["tool"] in ["rag", "chat"]
assert 0 <= result["confidence"] <= 1
print("JSON 格式验证通过")
```

Run: `python -c "import json; print(json.loads('{\"tool\": \"rag\", \"confidence\": 0.9, \"reasoning\": \"测试\"}'))"`

---

## Task 2: 修改 reasoning.py - JSON 解析 + Fallback

**Files:**
- Modify: `agent/core/reasoning.py:180-218`
- Test: `agent/core/test_reasoning.py`

- [ ] **Step 1: 编写 JSON 解析函数**

在 `ReasoningEngine` 类中添加新方法 `parse_tool_choice_json()`：

```python
def parse_tool_choice_json(self, llm_response: str) -> tuple[str, float, str]:
    """
    解析 JSON 格式的工具选择

    Args:
        llm_response: LLM 的原始输出（期望是 JSON）

    Returns:
        (tool_name, confidence, reasoning)
    """
    import json

    # 尝试提取 JSON（LLM 可能输出额外文本）
    json_match = re.search(r'\{[^{}]*"tool"[^{}]*\}', llm_response, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            tool = result.get("tool", "").lower()
            confidence = result.get("confidence", 0.5)
            reasoning = result.get("reasoning", "")

            # 验证 tool 有效性
            if tool in ["rag", "chat"]:
                return tool, confidence, reasoning
        except json.JSONDecodeError:
            pass

    # JSON 解析失败，返回默认值
    return "chat", 0.0, ""
```

- [ ] **Step 2: 修改 parse_tool_choice() 支持 JSON + Fallback**

将原有的正则解析方法保留，但优先尝试 JSON：

```python
def parse_tool_choice(self, llm_response: str) -> tuple[str, float, str]:
    """
    解析 LLM 的工具选择

    策略：
    1. 优先尝试 JSON 解析（结构化输出）
    2. JSON 解析失败时 fallback 到正则解析

    Args:
        llm_response: LLM 的原始输出

    Returns:
        (tool_name, confidence, reasoning)
    """
    # 首先尝试 JSON 解析
    tool, confidence, reasoning = self.parse_tool_choice_json(llm_response)
    if confidence > 0:
        return tool, confidence, reasoning

    # JSON 解析失败，fallback 到正则解析
    llm_lower = llm_response.lower()

    # 第一级：高置信度
    for pattern, conf in self.HIGH_CONF_PATTERNS:
        match = re.search(pattern, llm_lower)
        if match:
            return match.group(1), conf, reasoning

    # 第二级：中置信度
    for pattern, conf in self.MEDIUM_CONF_PATTERNS:
        match = re.search(pattern, llm_lower)
        if match:
            return match.group(1), conf, reasoning

    # 第三级：低置信度关键词
    if 'rag' in llm_lower and 'chat' not in llm_lower:
        return "rag", 0.40, reasoning
    elif 'chat' in llm_lower:
        return "chat", 0.40, reasoning

    # 无匹配：默认 chat
    return "chat", 0.0, reasoning
```

- [ ] **Step 3: 编写测试用例**

创建 `agent/core/test_reasoning.py`：

```python
"""
Reasoning Engine 测试
"""
import pytest
from agent.core.reasoning import ReasoningEngine


class TestParseToolChoice:
    """测试工具选择解析"""

    def setup_method(self):
        self.engine = ReasoningEngine()

    def test_json_format_rag(self):
        """测试 JSON 格式 - rag"""
        response = '{"tool": "rag", "confidence": 0.9, "reasoning": "询问法律条文"}'
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "rag"
        assert confidence == 0.9
        assert reasoning == "询问法律条文"

    def test_json_format_chat(self):
        """测试 JSON 格式 - chat"""
        response = '{"tool": "chat", "confidence": 0.95, "reasoning": "日常聊天"}'
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "chat"
        assert confidence == 0.95

    def test_json_with_extra_text(self):
        """测试 JSON 前后有额外文本"""
        response = '好的，我来分析一下。{"tool": "rag", "confidence": 0.8, "reasoning": "测试"}请注意'
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "rag"
        assert confidence == 0.8

    def test_invalid_json_fallback_to_regex(self):
        """测试无效 JSON fallback 到正则"""
        response = "我应该使用 rag 工具来回答这个问题"
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "rag"
        assert confidence == 0.70  # 中置信度

    def test_old_format_brackets(self):
        """测试旧格式 [[rag]]"""
        response = "工具选择: [[rag]]"
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "rag"
        assert confidence == 0.95  # 高置信度

    def test_old_format_keyword(self):
        """测试旧格式关键词"""
        response = "这个问题需要查询 rag"
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "rag"
        assert confidence == 0.40  # 低置信度

    def test_chat_fallback(self):
        """测试无匹配默认 chat"""
        response = "今天天气真好"
        tool, confidence, reasoning = self.engine.parse_tool_choice(response)
        assert tool == "chat"
        assert confidence == 0.0  # 默认值


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 4: 运行测试验证**

Run: `python -m pytest agent/core/test_reasoning.py -v`

Expected: 7 tests pass

---

## Task 3: 修改 controller.py - 适配新的返回值

**Files:**
- Modify: `agent/controller.py:112-138`
- Test: `agent/core/test_reasoning.py`

- [ ] **Step 1: 更新 parse_tool_choice 调用**

当前代码：
```python
tool_choice, confidence = self.reasoning_engine.parse_tool_choice(reasoning_response)
```

修改为：
```python
tool_choice, confidence, reasoning = self.reasoning_engine.parse_tool_choice(reasoning_response)
```

- [ ] **Step 2: 确认 record_result 调用兼容**

当前代码：
```python
state.record_result(
    tool_choice=tool_choice,
    confidence=confidence,
    reasoning_output=reasoning_output
)
```

`ReasoningState.record_result()` 的 `reasoning_output` 参数接受任意字符串，新的返回值 `reasoning` 可直接传入。

- [ ] **Step 3: 更新返回值的 reasoning 字段**

如果 `reasoning` 不为空，使用 LLM 返回的 reasoning；否则使用 `tool_choice.reasoning`。

```python
# 生成推理摘要
reasoning_summary = self._generate_reasoning_summary(state)
# 如果 LLM 返回了 reasoning，使用它
if reasoning and state.history:
    state.history[-1].reasoning = reasoning
```

- [ ] **Step 4: 运行集成测试**

Run: `python -c "from agent.controller import AgentController; print('Controller imports OK')"`

Expected: 无报错

---

## Task 4: 验证测试

**Files:**
- Test: `test/test_agent.py`

- [ ] **Step 1: 更新测试脚本**

当前 `test/test_agent.py` 使用旧的导入路径，需要确认导入正确：

```bash
grep -n "from agent" test/test_agent.py
```

应该显示：
```
from agent.controller import AgentController
```

- [ ] **Step 2: 运行完整测试**

Run: `python test/test_agent.py`

Expected: 测试函数正常执行，无报错

---

## Task 5: 提交代码

- [ ] **Step 1: 检查改动**

Run: `git diff --stat`

Expected: 显示修改的文件

- [ ] **Step 2: 提交**

```bash
git add agent/react_prompt.py agent/core/reasoning.py agent/controller.py agent/core/test_reasoning.py
git commit -m "feat: Agent 结构化输出 - JSON 格式工具选择

- 修改 react_prompt.py，新增 JSON 输出提示词
- 修改 reasoning.py，parse_tool_choice() 支持 JSON 解析 + 正则 fallback
- 修改 controller.py，适配新的返回值格式
- 新增 test_reasoning.py 测试用例

BREAKING CHANGE: parse_tool_choice() 返回值从 (tool, conf) 变为 (tool, conf, reasoning)
"
```

---

## 验证清单

- [ ] JSON 格式提示词能正确引导 LLM 输出
- [ ] JSON 解析能正确提取 tool、confidence、reasoning
- [ ] JSON 解析失败时正确 fallback 到正则
- [ ] 旧格式（[[rag]]、自然语言）仍能正确解析
- [ ] Controller 适配新的返回值
- [ ] 集成测试通过
- [ ] 代码已提交

---

## 面试可讲内容

1. **问题发现**：正则匹配脆弱，LLM 输出格式变化会导致解析失败
2. **解决方案**：改用结构化输出，LLM 返回 JSON 格式
3. **兼容性设计**：JSON 解析优先，保留正则 fallback，双重保障
4. **工程思维**：从"被动防御"到"主动规范"，不依赖 LLM 的固定格式
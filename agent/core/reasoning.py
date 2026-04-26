"""
推理状态管理模块

管理 ReAct 循环中的推理状态：
- 当前轮次
- 推理历史
- 上下文追踪
- 决策记录
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ToolType(Enum):
    """工具类型枚举"""
    RAG = "rag"
    CHAT = "chat"


@dataclass
class ReasoningStep:
    """单轮推理步骤"""
    iteration: int                    # 第几轮迭代
    tool_choice: str                  # 选择的工具：rag / chat
    confidence: float                 # 置信度：0.0-1.0
    reasoning_output: str            # LLM 的推理输出
    tool_result: Optional[str] = None  # 工具执行结果
    execution_time: Optional[float] = None  # 执行耗时（秒）
    is_timeout: bool = False          # 是否超时
    evaluation: Optional[str] = None  # 质量评估结果：充分/不充分


@dataclass
class ReasoningState:
    """
    推理状态管理器

    职责：
    1. 追踪当前迭代轮次
    2. 记录每轮推理详情
    3. 维护推理历史
    4. 提供状态查询接口
    """

    max_iterations: int = 3                    # 最大迭代次数
    current_iteration: int = 0                 # 当前轮次
    query: str = ""                            # 用户原始问题
    session_id: str = ""                       # 会话ID
    history: List[ReasoningStep] = field(default_factory=list)  # 推理历史
    final_response: Optional[str] = None       # 最终回答
    tool_used: Optional[str] = None            # 最终使用的工具

    def start_new_iteration(self) -> int:
        """开始新一轮迭代，返回当前轮次"""
        self.current_iteration += 1
        return self.current_iteration

    def add_step(self, step: ReasoningStep):
        """添加一轮推理记录"""
        self.history.append(step)

    def get_last_step(self) -> Optional[ReasoningStep]:
        """获取上一轮推理记录"""
        return self.history[-1] if self.history else None

    def is_max_iterations_reached(self) -> bool:
        """是否达到最大迭代次数"""
        return self.current_iteration >= self.max_iterations

    def should_continue(self) -> bool:
        """是否应该继续循环"""
        if self.is_max_iterations_reached():
            return False
        last = self.get_last_step()
        if last is None:
            return True
        # 如果上轮结果"充分"，停止循环
        if last.evaluation in ["充分", "满意", "足够"]:
            return False
        return True

    def record_result(self, tool_choice: str, confidence: float,
                     reasoning_output: str, tool_result: str = None,
                     execution_time: float = None, is_timeout: bool = False):
        """
        记录一轮推理的执行结果

        Args:
            tool_choice: 选择的工具
            confidence: 置信度
            reasoning_output: LLM 推理输出
            tool_result: 工具执行结果
            execution_time: 执行耗时
            is_timeout: 是否超时
        """
        step = ReasoningStep(
            iteration=self.current_iteration,
            tool_choice=tool_choice,
            confidence=confidence,
            reasoning_output=reasoning_output,
            tool_result=tool_result,
            execution_time=execution_time,
            is_timeout=is_timeout
        )
        self.add_step(step)

    def record_evaluation(self, evaluation: str):
        """
        记录质量评估结果

        Args:
            evaluation: 评估结果：充分/不充分
        """
        if self.history:
            self.history[-1].evaluation = evaluation

    def to_summary(self) -> Dict[str, Any]:
        """
        生成推理状态摘要（用于调试和日志）

        Returns:
            {
                "current_iteration": int,
                "max_iterations": int,
                "steps_count": int,
                "tool_used": str,
                "final_response": str,
                "timeout_count": int,
                "is_success": bool
            }
        """
        timeout_count = sum(1 for step in self.history if step.is_timeout)
        return {
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "steps_count": len(self.history),
            "tool_used": self.tool_used,
            "final_response": self.final_response,
            "timeout_count": timeout_count,
            "is_success": self.final_response is not None
        }

    def reset(self):
        """重置状态（用于新的对话）"""
        self.current_iteration = 0
        self.history.clear()
        self.final_response = None
        self.tool_used = None


class ReasoningEngine:
    """
    推理引擎

    负责：
    1. 构建 ReAct 提示词
    2. 解析 LLM 推理输出
    3. 提供推理辅助方法
    """

    # 高置信度模式：明确的指令格式
    HIGH_CONF_PATTERNS = [
        (r'\[\[(rag|chat)\]\]', 0.95),
        (r'<tool>\s*(rag|chat)\s*</tool>', 0.95),
        (r'工具选择\s*[:：]\s*(rag|chat)', 0.90),
        (r'选择\s*(rag|chat)\s*工具', 0.85),
    ]

    # 中置信度模式：自然语言提及
    MEDIUM_CONF_PATTERNS = [
        (r'使用\s+(rag|chat)\s+工具', 0.70),
        (r'调用\s+(rag|chat)', 0.65),
        (r'应该用\s+(rag|chat)', 0.60),
    ]

    def __init__(self):
        pass

    def parse_tool_choice_json(self, llm_response: str) -> tuple[str, float, str]:
        """
        解析 JSON 格式的工具选择

        Args:
            llm_response: LLM 的原始输出（期望是 JSON）

        Returns:
            (tool_name, confidence, reasoning)
        """
        import json
        import re

        # 更健壮的 JSON 提取：处理嵌套情况
        # 尝试找到最外层的 { ... } 然后从中提取 tool
        try:
            # 尝试解析整个响应为 JSON
            try:
                result = json.loads(llm_response)
            except json.JSONDecodeError:
                # 如果失败，尝试提取 JSON 对象
                json_match = re.search(r'\{[\s\S]*\}', llm_response)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    return "chat", 0.0, ""
        except json.JSONDecodeError:
            return "chat", 0.0, ""

        # 提取字段
        tool = result.get("tool", "").lower()
        confidence = result.get("confidence", 0.5)
        reasoning = result.get("reasoning", "")

        # 类型转换：确保 confidence 是 float
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.5

        # 验证 tool 有效性
        if tool in ["rag", "chat"]:
            return tool, confidence, reasoning

        # tool 无效，返回默认值（不触发 fallback，保留原始 response 信息）
        return "chat", 0.0, ""

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
        import re

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
                return match.group(1), conf, llm_response[:100]  # 保留原始文本片段

        # 第二级：中置信度
        for pattern, conf in self.MEDIUM_CONF_PATTERNS:
            match = re.search(pattern, llm_lower)
            if match:
                return match.group(1), conf, llm_response[:100]

        # 第三级：低置信度关键词
        if 'rag' in llm_lower and 'chat' not in llm_lower:
            return "rag", 0.40, llm_response[:100]
        elif 'chat' in llm_lower:
            return "chat", 0.40, llm_response[:100]

        # 无匹配：默认 chat
        return "chat", 0.0, ""

    def build_reflection_prompt(self, query: str, tool_result: str) -> str:
        """
        构建反思提示词

        Args:
            query: 用户原始问题
            tool_result: 工具执行结果

        Returns:
            反思提示词字符串
        """
        return f"""判断以下回答是否充分回答了用户问题。

用户问题：{query}
上一轮回答：{tool_result}

如果回答已经充分回答了用户的问题，返回"充分"。
如果回答不充分或没有真正回答问题，返回"不充分"，并简要说明原因。

你的判断："""

    def build_retry_context(self, query: str, history: List[ReasoningStep]) -> str:
        """
        构建重试上下文（用于下一轮推理）

        将之前的推理历史整合成上下文信息

        Args:
            query: 用户原始问题
            history: 推理历史

        Returns:
            上下文字符串
        """
        context_parts = [f"用户问题：{query}"]

        for i, step in enumerate(history, 1):
            context_parts.append(f"\n第{i}轮推理：")
            context_parts.append(f"  - 选择工具：{step.tool_choice}（置信度：{step.confidence}）")
            if step.tool_result:
                context_parts.append(f"  - 执行结果：{step.tool_result[:200]}...")  # 截断避免太长
            if step.is_timeout:
                context_parts.append(f"  - 状态：超时")
            else:
                context_parts.append(f"  - 状态：完成")
            if step.evaluation:
                context_parts.append(f"  - 评估：{step.evaluation}")

        context_parts.append("\n请根据以上信息，重新分析并给出更好的回答。")
        return "\n".join(context_parts)
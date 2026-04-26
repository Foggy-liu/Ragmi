"""
结果质量评估模块

负责：
1. 评估工具执行结果的质量
2. 判断回答是否充分
3. 触发自我纠错（self-correction）机制
"""
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class QualityLevel(Enum):
    """质量等级枚举"""
    EXCELLENT = "excellent"   # 优秀：完全满足需求
    GOOD = "good"             # 良好：基本满足需求
    ACCEPTABLE = "acceptable"  # 可接受：部分满足需求
    POOR = "poor"             # 较差：未能满足需求
    FAILED = "failed"         # 失败：完全无法满足


@dataclass
class EvaluationResult:
    """
    评估结果

    包含评估的所有信息，用于决策是否继续循环
    """
    is_sufficient: bool       # 是否充分
    quality_level: QualityLevel  # 质量等级
    reason: str               # 评估理由
    suggestion: Optional[str] = None  # 改进建议（如果有）


class QualityEvaluator:
    """
    质量评估器

    职责：
    1. 基于规则快速评估结果质量
    2. 调用 LLM 进行深度评估（Reflection）
    3. 生成改进建议
    """

    # 快速判断规则
    FAIL_PATTERNS = [
        "无法回答", "不知道", "我没有", "无法提供",
        "不在知识库中", "没有找到", "无法检索",
        "抱歉", "错误", "失败", "超时"
    ]

    SUCCESS_PATTERNS = [
        "根据", "检索到", "文档显示", "依据",
        "找到", "相关", "如下"
    ]

    def __init__(self):
        pass

    def evaluate_rapid(self, response: str) -> EvaluationResult:
        """
        快速评估（基于规则）

        用于第一轮快速判断，避免不必要的 LLM 调用

        Args:
            response: 工具执行结果

        Returns:
            EvaluationResult: 评估结果
        """
        response_lower = response.lower()

        # 检查是否包含失败模式
        for pattern in self.FAIL_PATTERNS:
            if pattern in response_lower:
                return EvaluationResult(
                    is_sufficient=False,
                    quality_level=QualityLevel.POOR,
                    reason=f"检测到失败模式：'{pattern}'",
                    suggestion="建议重新检索或换用其他工具"
                )

        # 检查是否包含成功模式
        has_success = any(pattern in response_lower for pattern in self.SUCCESS_PATTERNS)

        # 检查响应长度
        is_too_short = len(response) < 10
        is_too_long = len(response) > 5000

        if is_too_short:
            return EvaluationResult(
                is_sufficient=False,
                quality_level=QualityLevel.POOR,
                reason="回答过短，可能未完成",
                suggestion="建议重新检索获取更完整的信息"
            )

        if has_success:
            return EvaluationResult(
                is_sufficient=True,
                quality_level=QualityLevel.GOOD,
                reason="检测到成功模式，回答较为完整"
            )

        # 无法快速判断，需要深度评估
        return EvaluationResult(
            is_sufficient=True,
            quality_level=QualityLevel.ACCEPTABLE,
            reason="无法快速判断，需要深度评估"
        )

    def evaluate_with_llm(
        self,
        query: str,
        tool_result: str,
        model
    ) -> EvaluationResult:
        """
        使用 LLM 进行深度评估（Reflection 机制）

        调用 LLM 判断回答是否充分

        Args:
            query: 用户原始问题
            tool_result: 工具执行结果
            model: LLM 模型实例

        Returns:
            EvaluationResult: 评估结果
        """
        from langchain_core.messages import HumanMessage

        reflection_prompt = f"""你是一个回答质量评估专家。

请评估以下回答是否充分回答了用户的问题。

用户问题：{query}

回答内容：{tool_result}

请从以下维度评估：
1. 准确性：回答是否准确围绕问题展开？
2. 完整性：回答是否涵盖了问题的主要方面？
3. 相关性：回答是否与问题相关？

然后给出你的判断：
- 如果回答充分，返回"充分"并说明理由
- 如果回答不充分，返回"不充分"并说明原因和修改建议

格式：
判断：充分/不充分
理由：[你的理由]
建议：[如果不够充分，你的修改建议]"""

        try:
            response = model.invoke([HumanMessage(content=reflection_prompt)])

            # 解析 LLM 返回
            response_lower = response.lower()

            if "不充分" in response_lower or "不满足" in response_lower:
                return EvaluationResult(
                    is_sufficient=False,
                    quality_level=QualityLevel.POOR,
                    reason="LLM 评估：不充分",
                    suggestion="建议重新检索或换用其他工具"
                )
            else:
                return EvaluationResult(
                    is_sufficient=True,
                    quality_level=QualityLevel.ACCEPTABLE,
                    reason="LLM 评估：充分"
                )

        except Exception as e:
            # LLM 调用失败，回退到快速评估
            return EvaluationResult(
                is_sufficient=False,
                quality_level=QualityLevel.POOR,
                reason=f"LLM 评估失败：{str(e)}",
                suggestion="建议使用快速评估结果"
            )

    def evaluate(
        self,
        query: str,
        tool_result: str,
        tool_name: str,
        model=None,
        use_rapid: bool = True
    ) -> EvaluationResult:
        """
        综合评估入口

        Args:
            query: 用户原始问题
            tool_result: 工具执行结果
            tool_name: 工具名称（用于调整评估策略）
            model: LLM 模型实例（用于深度评估），None 则只用快速评估
            use_rapid: 是否使用快速评估

        Returns:
            EvaluationResult: 评估结果
        """
        # 如果 RAG 返回空或超时，直接判定为不充分
        if not tool_result or len(tool_result.strip()) == 0:
            return EvaluationResult(
                is_sufficient=False,
                quality_level=QualityLevel.FAILED,
                reason="回答为空",
                suggestion="建议换用其他工具获取回答"
            )

        # 先用快速评估
        if use_rapid:
            rapid_result = self.evaluate_rapid(tool_result)
            if rapid_result.quality_level == QualityLevel.POOR:
                # 快速评估已经判断为不充分，不需要 LLM 评估
                return rapid_result

        # 如果提供了 LLM 模型，进行深度评估
        if model is not None:
            return self.evaluate_with_llm(query, tool_result, model)
        else:
            # 没有 LLM 模型，使用快速评估结果
            return rapid_result if use_rapid else EvaluationResult(
                is_sufficient=True,
                quality_level=QualityLevel.ACCEPTABLE,
                reason="无法评估（无 LLM 模型）"
            )

    def should_retry(self, evaluation: EvaluationResult, retry_count: int, max_retries: int = 2) -> bool:
        """
        判断是否应该重试

        Args:
            evaluation: 评估结果
            retry_count: 当前重试次数
            max_retries: 最大重试次数

        Returns:
            bool: 是否应该继续重试
        """
        if retry_count >= max_retries:
            return False

        if not evaluation.is_sufficient:
            return True

        if evaluation.quality_level == QualityLevel.POOR:
            return True

        return False

    def get_improvement_suggestion(self, evaluation: EvaluationResult, tool_name: str) -> str:
        """
        根据评估结果生成改进建议

        Args:
            evaluation: 评估结果
            tool_name: 当前使用的工具

        Returns:
            str: 改进建议
        """
        if evaluation.is_sufficient:
            return "当前回答已足够，无需改进"

        if tool_name == "rag":
            suggestions = [
                "尝试扩大检索范围",
                "换用其他文档片段",
                "考虑换用 chat 工具直接回答"
            ]
        else:  # chat
            suggestions = [
                "尝试重新组织回答",
                "考虑换用 rag 工具获取更准确的信息"
            ]

        return suggestions[0] if evaluation.suggestion is None else evaluation.suggestion
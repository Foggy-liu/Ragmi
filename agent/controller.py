"""
Agent 控制器

重载后的 Controller 作为编排层，协调 core 和 tools

职责：
1. 初始化和组装各个组件
2. 执行 ReAct 循环
3. 处理超时和降级
4. 返回统一格式的结果
"""
from typing import Dict, Any, Optional
from utils.message.message import MessageManager
from utils.models.model_manager import ModelManager
from agent.base.tool import BaseTool
from agent.tools.rag_tool import RagTool
from agent.tools.chat_tool import ChatTool
from agent.react_prompt import REACT_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT_LITE
from agent.core.reasoning import ReasoningState, ReasoningEngine
from agent.core.strategy import ToolStrategy, ToolResult, ExecutionStatus
from agent.core.evaluation import QualityEvaluator, EvaluationResult


class AgentController:
    """
    Agent 控制器（编排层）

    协调 ReasoningState、ToolStrategy、QualityEvaluator 和 Tool 执行

    ReAct 循环流程：
    1. Reasoning - LLM 分析问题，决定工具
    2. Acting - 执行工具（带超时控制）
    3. Observation - 获取执行结果
    4. Evaluation - 评估结果质量
    5. 如果不充分 → 继续循环或降级
    """

    def __init__(self, model_manager: ModelManager, use_lite: bool = False,
                 timeout: float = 120.0, max_retries: int = 1):
        """
        初始化 Agent 控制器

        Args:
            model_manager: 模型管理器
            use_lite: 是否使用简化版提示词
            timeout: 默认超时时间（秒，默认 120 适配 RAG）
            max_retries: 最大重试次数
        """
        self.model_manager = model_manager
        self.msg_manager = MessageManager()

        # 初始化工具
        self.tools: Dict[str, BaseTool] = {
            "rag": RagTool(model_manager),
            "chat": ChatTool(model_manager),
        }

        # 选择提示词版本
        self.system_prompt = REACT_SYSTEM_PROMPT_LITE if use_lite else REACT_SYSTEM_PROMPT

        # 初始化核心组件
        self.reasoning_engine = ReasoningEngine()
        self.tool_strategy = ToolStrategy(timeout=timeout, max_retries=max_retries)
        self.quality_evaluator = QualityEvaluator()

    def decide_and_act(self, query: str, session_id: Optional[str] = None,
                       max_iterations: int = 3) -> Dict[str, Any]:
        """
        ReAct 核心循环

        流程：
        1. 初始化推理状态
        2. 循环执行 ReAct：
           - Reasoning: LLM 分析问题，决定工具
           - Acting: 执行工具（带超时和降级）
           - Observation: 获取执行结果
           - Evaluation: 评估结果质量
        3. 达到条件则结束循环

        Args:
            query: 用户问题
            session_id: 会话ID
            max_iterations: 最大迭代次数

        Returns:
            {
                "response": str,           # 最终回答
                "session_id": str,        # 会话ID
                "tool_used": str,          # 使用的工具
                "iterations": int,         # 迭代次数
                "reasoning": str           # 推理过程摘要
            }
        """
        # 初始化会话
        session_id = self.msg_manager.ensure_session(session_id)

        # 初始化推理状态
        state = ReasoningState(
            max_iterations=max_iterations,
            query=query,
            session_id=session_id
        )

        # 构建初始消息
        messages = self.msg_manager.build_messages(
            session_id,
            query,
            custom_system=self.system_prompt
        )

        # ============ ReAct 循环 ============
        while state.should_continue():
            # 开始新一轮迭代
            iteration = state.start_new_iteration()

            # ------- Step 1: Reasoning -------
            model = self.model_manager.get_current_model()
            reasoning_response = model.invoke(messages)

            # 解析工具选择
            tool_choice, confidence, reasoning = self.reasoning_engine.parse_tool_choice(reasoning_response)

            # 如果 LLM 返回了 reasoning，使用它；否则使用完整的 reasoning_response
            reasoning_for_record = reasoning if reasoning else str(reasoning_response)
            state.record_result(
                tool_choice=tool_choice,
                confidence=confidence,
                reasoning_output=reasoning_for_record
            )

            # 如果是超时后的重试，添加重试上下文
            last_step = state.get_last_step()
            if last_step and last_step.is_timeout:
                retry_context = self.reasoning_engine.build_retry_context(
                    query, state.history[:-1]
                )
                messages.append({"role": "user", "content": retry_context})

            # ------- Step 2: Acting -------
            # 根据置信度决定是否执行选择的工具
            if confidence < 0.5:
                # 置信度低，使用默认工具 chat
                chosen_tool = "chat"
            else:
                chosen_tool = tool_choice

            # 执行工具（带超时控制）
            tool_func = self._get_tool_func(chosen_tool)
            tool_result = self.tool_strategy.execute_with_timeout(
                tool_func=tool_func,
                tool_name=chosen_tool,
                query=query,
                session_id=session_id
            )

            # 更新推理状态中的工具结果
            last_step = state.get_last_step()
            if last_step:
                last_step.tool_result = tool_result.response
                last_step.execution_time = tool_result.execution_time
                last_step.is_timeout = (tool_result.status == ExecutionStatus.TIMEOUT)

            # ------- Step 3: Observation -------
            if tool_result.status == ExecutionStatus.TIMEOUT:
                # 超时：记录状态，准备降级
                if chosen_tool == "rag" and iteration < max_iterations:
                    # RAG 超时，尝试换 chat
                    continue
                else:
                    # 已达最大迭代或非 RAG 工具，强制结束
                    state.final_response = f"处理超时，请稍后重试。"
                    state.tool_used = chosen_tool
                    break

            if tool_result.status == ExecutionStatus.ERROR:
                # 执行错误：记录状态
                if chosen_tool == "rag" and iteration < max_iterations:
                    # RAG 错误，尝试换 chat
                    continue
                else:
                    state.final_response = f"处理失败：{tool_result.error_message}"
                    state.tool_used = chosen_tool
                    break

            # ------- Step 4: Evaluation -------
            evaluation = self.quality_evaluator.evaluate(
                query=query,
                tool_result=tool_result.response,
                tool_name=chosen_tool,
                model=model
            )
            state.record_evaluation("充分" if evaluation.is_sufficient else "不充分")

            # 评估结果判断
            if evaluation.is_sufficient:
                # 结果充分，结束循环
                state.final_response = tool_result.response
                state.tool_used = tool_result.tool_name
                break
            else:
                # 结果不充分，添加上下文继续循环
                if state.is_max_iterations_reached():
                    # 达到最大迭代次数
                    state.final_response = tool_result.response
                    state.tool_used = tool_result.tool_name
                    break

                # 添加反思信息到消息中
                retry_message = (
                    f"上一轮回答不充分，请重新分析并回答。\n"
                    f"用户问题：{query}\n"
                    f"上一轮回答：{tool_result.response}\n"
                    f"不充分原因：{evaluation.reason}\n"
                    f"建议：{evaluation.suggestion or '请换用其他工具或重新组织回答'}"
                )
                messages.append({"role": "user", "content": retry_message})

        # 如果循环结束但没有结果（超时场景），尝试降级
        if state.final_response is None and state.current_iteration > 0:
            last_step = state.get_last_step()
            if last_step and last_step.is_timeout:
                # 降级执行 chat
                chat_result = self.tool_strategy.execute_with_timeout(
                    tool_func=self._get_tool_func("chat"),
                    tool_name="chat",
                    query=query,
                    session_id=session_id
                )
                state.final_response = chat_result.response
                state.tool_used = "chat (降级)"

        # 保存对话历史
        if state.final_response:
            self.msg_manager.add_to_history(session_id, query, state.final_response)

        # 生成推理摘要
        reasoning_summary = self._generate_reasoning_summary(state)

        return {
            "response": state.final_response or "处理失败",
            "session_id": session_id,
            "tool_used": state.tool_used or "unknown",
            "iterations": state.current_iteration,
            "reasoning": reasoning_summary
        }

    def _get_tool_func(self, tool_name: str):
        """
        获取工具执行函数

        Args:
            tool_name: 工具名称

        Returns:
            工具执行函数
        """
        if tool_name not in self.tools:
            tool_name = "chat"  # 默认降级到 chat

        tool = self.tools[tool_name]

        def func(query: str, session_id: Optional[str] = None):
            return tool.invoke(query, session_id)

        return func

    def _generate_reasoning_summary(self, state: ReasoningState) -> str:
        """
        生成推理过程摘要

        用于返回给前端或日志记录

        Args:
            state: 推理状态

        Returns:
            推理摘要字符串
        """
        summary_parts = [f"共进行 {state.current_iteration} 轮推理"]

        for step in state.history:
            status = "超时" if step.is_timeout else f"置信度 {step.confidence}"
            summary_parts.append(
                f"第{step.iteration}轮：选择 {step.tool_choice}（{status}）"
            )

        if state.final_response:
            summary_parts.append(f"最终使用工具：{state.tool_used}")

        return " | ".join(summary_parts)

    def get_tools_info(self) -> Dict[str, Any]:
        """
        获取工具信息

        Returns:
            工具信息字典
        """
        return {
            "tools": list(self.tools.keys()),
            "tool_descriptions": {
                "rag": "基于知识库的问答工具，检索文档内容回答",
                "chat": "普通对话工具，用于日常聊天和通用问题"
            },
            "strategy_stats": self.tool_strategy.get_stats()
        }
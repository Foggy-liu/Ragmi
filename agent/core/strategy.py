"""
工具调度策略模块

负责：
1. 工具调用决策
2. 超时处理
3. Fallback 机制
4. 重试策略
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable
from enum import Enum
import time


class ExecutionStatus(Enum):
    """执行状态枚举"""
    SUCCESS = "success"           # 成功
    TIMEOUT = "timeout"           # 超时
    ERROR = "error"               # 错误
    FALLBACK = "fallback"         # 降级执行


@dataclass
class ToolResult:
    """
    工具执行结果

    包含执行的所有信息，用于后续评估和决策
    """
    response: str                  # 工具返回的回答
    tool_name: str               # 工具名称：rag / chat
    confidence: str               # 置信度说明
    execution_time: float         # 执行耗时（秒）
    status: ExecutionStatus       # 执行状态
    error_message: Optional[str] = None  # 错误信息（如果有）
    is_fallback: bool = False     # 是否是降级执行


@dataclass
class ToolConfig:
    """工具配置"""
    timeout: float = 30.0         # 超时时间（秒）
    max_retries: int = 1         # 最大重试次数
    retry_on_timeout: bool = True # 超时是否重试


class ToolStrategy:
    """
    工具调度策略管理器

    职责：
    1. 管理工具配置（超时时间、重试次数）
    2. 执行工具调用
    3. 处理超时和降级
    4. 提供执行统计
    """

    # 默认工具配置
    DEFAULT_RAG_CONFIG = ToolConfig(
        timeout=120.0,             # RAG: embedding + search + LLM 通常 30-90s
        max_retries=1,
        retry_on_timeout=True
    )

    DEFAULT_CHAT_CONFIG = ToolConfig(
        timeout=60.0,              # Chat: 单次 LLM 通常 10-30s
        max_retries=1,
        retry_on_timeout=False  # Chat 通常不会超时
    )

    def __init__(self, timeout: float = 30.0, max_retries: int = 1):
        """
        初始化策略管理器

        Args:
            timeout: 默认超时时间（秒）
            max_retries: 默认最大重试次数
        """
        self.timeout = timeout
        self.max_retries = max_retries

        # 各工具配置
        self.tool_configs: Dict[str, ToolConfig] = {
            "rag": ToolConfig(timeout=timeout, max_retries=max_retries),
            "chat": ToolConfig(timeout=60.0, max_retries=1),
        }

        # 执行统计
        self.stats = {
            "rag_success": 0,
            "rag_timeout": 0,
            "rag_error": 0,
            "chat_success": 0,
            "chat_timeout": 0,
            "chat_error": 0,
        }

    def execute_with_timeout(
        self,
        tool_func: Callable,
        tool_name: str,
        query: str,
        session_id: Optional[str] = None,
        timeout: float = None
    ) -> ToolResult:
        """
        带超时控制的工具执行

        Args:
            tool_func: 工具执行函数
            tool_name: 工具名称：rag / chat
            query: 用户问题
            session_id: 会话ID
            timeout: 超时时间（秒），None 则使用默认值

        Returns:
            ToolResult: 执行结果
        """
        config = self.tool_configs.get(tool_name, self.DEFAULT_RAG_CONFIG)
        timeout = timeout or config.timeout

        start_time = time.time()
        error_message = None

        try:
            # 使用 timeout 装饰器或线程执行来实现超时控制
            result = self._execute_with_timeout_impl(
                tool_func, query, session_id, timeout
            )

            execution_time = time.time() - start_time

            # 解析返回结果
            response = result.get("response", "")
            confidence = result.get("confidence", "未知")

            return ToolResult(
                response=response,
                tool_name=tool_name,
                confidence=confidence,
                execution_time=execution_time,
                status=ExecutionStatus.SUCCESS
            )

        except TimeoutError:
            # 超时处理
            execution_time = time.time() - start_time
            self._record_stats(tool_name, ExecutionStatus.TIMEOUT)

            return ToolResult(
                response="",
                tool_name=tool_name,
                confidence="超时",
                execution_time=execution_time,
                status=ExecutionStatus.TIMEOUT,
                error_message=f"执行超时（{timeout}秒）"
            )

        except Exception as e:
            # 错误处理
            execution_time = time.time() - start_time
            error_message = str(e)
            self._record_stats(tool_name, ExecutionStatus.ERROR)

            return ToolResult(
                response="",
                tool_name=tool_name,
                confidence="错误",
                execution_time=execution_time,
                status=ExecutionStatus.ERROR,
                error_message=error_message
            )

    def _execute_with_timeout_impl(
        self,
        tool_func: Callable,
        query: str,
        session_id: Optional[str],
        timeout: float
    ):
        """
        实际执行工具调用（带超时）

        使用线程 + 事件机制实现超时控制

        Args:
            tool_func: 工具执行函数
            query: 用户问题
            session_id: 会话ID
            timeout: 超时时间

        Returns:
            工具返回结果

        Raises:
            TimeoutError: 执行超时
        """
        import threading

        result_container = [None]
        exception_container = [None]

        def target():
            try:
                result_container[0] = tool_func(query, session_id)
            except Exception as e:
                exception_container[0] = e

        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 线程仍在运行，说明超时了
            raise TimeoutError(f"工具执行超过 {timeout} 秒")

        if exception_container[0]:
            # 执行过程中出现异常
            raise exception_container[0]

        if result_container[0] is None:
            raise Exception("工具执行返回为空")

        return result_container[0]

    def execute_with_retry(
        self,
        tool_func: Callable,
        tool_name: str,
        query: str,
        session_id: Optional[str] = None,
        max_retries: int = None
    ) -> ToolResult:
        """
        带重试的工具执行

        Args:
            tool_func: 工具执行函数
            tool_name: 工具名称
            query: 用户问题
            session_id: 会话ID
            max_retries: 最大重试次数，None 则使用配置默认值

        Returns:
            ToolResult: 执行结果
        """
        config = self.tool_configs.get(tool_name, self.DEFAULT_RAG_CONFIG)
        max_retries = max_retries or config.max_retries

        last_result = None

        for attempt in range(max_retries + 1):
            result = self.execute_with_timeout(
                tool_func=tool_func,
                tool_name=tool_name,
                query=query,
                session_id=session_id
            )

            last_result = result

            if result.status == ExecutionStatus.SUCCESS:
                # 成功，直接返回
                return result

            if result.status == ExecutionStatus.TIMEOUT:
                # 超时，尝试重试
                if attempt < max_retries:
                    continue  # 继续重试
                else:
                    # 达到最大重试次数，返回失败结果
                    return result

            if result.status == ExecutionStatus.ERROR:
                # 错误，不重试，直接返回
                return result

        return last_result

    def execute_with_fallback(
        self,
        primary_tool_func: Callable,
        fallback_tool_func: Callable,
        primary_tool_name: str,
        query: str,
        session_id: Optional[str] = None
    ) -> ToolResult:
        """
        带降级的工具执行

        当主工具超时时，自动切换到备用工具

        Args:
            primary_tool_func: 主工具执行函数（RAG）
            fallback_tool_func: 备用工具执行函数（Chat）
            primary_tool_name: 主工具名称
            query: 用户问题
            session_id: 会话ID

        Returns:
            ToolResult: 执行结果
        """
        # 首先尝试主工具（RAG）
        result = self.execute_with_timeout(
            tool_func=primary_tool_func,
            tool_name=primary_tool_name,
            query=query,
            session_id=session_id
        )

        if result.status == ExecutionStatus.SUCCESS:
            # 主工具成功
            return result

        # 主工具失败或超时，尝试备用工具（Chat）
        fallback_result = self.execute_with_timeout(
            tool_func=fallback_tool_func,
            tool_name="chat",
            query=query,
            session_id=session_id
        )

        # 标记为降级执行
        fallback_result.is_fallback = True

        return fallback_result

    def get_stats(self) -> Dict[str, Any]:
        """
        获取执行统计

        Returns:
            执行统计字典
        """
        total_rag = (self.stats["rag_success"] +
                     self.stats["rag_timeout"] +
                     self.stats["rag_error"])
        total_chat = (self.stats["chat_success"] +
                      self.stats["chat_timeout"] +
                      self.stats["chat_error"])

        return {
            "rag": {
                "total": total_rag,
                "success": self.stats["rag_success"],
                "timeout": self.stats["rag_timeout"],
                "error": self.stats["rag_error"],
                "success_rate": self.stats["rag_success"] / total_rag if total_rag > 0 else 0
            },
            "chat": {
                "total": total_chat,
                "success": self.stats["chat_success"],
                "timeout": self.stats["chat_timeout"],
                "error": self.stats["chat_error"],
                "success_rate": self.stats["chat_success"] / total_chat if total_chat > 0 else 0
            }
        }

    def _record_stats(self, tool_name: str, status: ExecutionStatus):
        """记录执行统计"""
        if tool_name == "rag":
            if status == ExecutionStatus.SUCCESS:
                self.stats["rag_success"] += 1
            elif status == ExecutionStatus.TIMEOUT:
                self.stats["rag_timeout"] += 1
            elif status == ExecutionStatus.ERROR:
                self.stats["rag_error"] += 1
        elif tool_name == "chat":
            if status == ExecutionStatus.SUCCESS:
                self.stats["chat_success"] += 1
            elif status == ExecutionStatus.TIMEOUT:
                self.stats["chat_timeout"] += 1
            elif status == ExecutionStatus.ERROR:
                self.stats["chat_error"] += 1
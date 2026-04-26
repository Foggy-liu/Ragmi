# NEW_FILE_CODE
"""
Agent API接口
提供 RESTful 接口供前端调用
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional
from .dependencies import get_model_manager
from agent.controller import AgentController

appagent = APIRouter()


class AgentRequest(BaseModel):
    """Agent请求模型"""
    query: str = Field(..., description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID")
    use_lite: bool = Field(False, description="是否使用简化版提示词")


class AgentResponse(BaseModel):
    """Agent响应模型"""
    response: str           # 最终回答
    session_id: str         # 会话ID
    tool_used: Optional[str] = None  # 使用的工具
    iterations: int = 1     # 迭代次数
    reasoning: Optional[str] = None  # 推理过程


def get_agent_controller(model_manager=Depends(get_model_manager)) -> AgentController:
    """获取Agent控制器实例"""
    return AgentController(model_manager)


@appagent.post("/agent/chat", response_model=AgentResponse)
async def agent_chat(
    request: AgentRequest,
    agent: AgentController = Depends(get_agent_controller)
) -> AgentResponse:
    """
    Agent智能对话接口

    流程：
    1. Reasoning - LLM分析问题，决定用什么工具
    2. Acting - 执行工具（RAG或Chat）
    3. Observation - 获取工具执行结果
    4. Reflection - 判断结果是否充分

    复杂问题会进行多轮ReAct循环（最多3轮）
    """
    result = agent.decide_and_act(
        query=request.query,
        session_id=request.session_id,
        max_iterations=3
    )

    return AgentResponse(
        response=result["response"],
        session_id=result["session_id"],
        tool_used=result.get("tool_used"),
        iterations=result.get("iterations", 1),
        reasoning=result.get("reasoning")
    )


@appagent.get("/agent/tools")
async def get_tools_info(agent: AgentController = Depends(get_agent_controller)):
    """获取工具信息"""
    return {
        "tools": list(agent.tools.keys()),
        "tool_descriptions": {
            "rag": "基于知识库的问答工具，检索文档内容回答",
            "chat": "普通对话工具，用于日常聊天和通用问题"
        }
    }

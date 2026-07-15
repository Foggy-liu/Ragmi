"""api/api_agent.py —— Agent FastAPI 路由。

暴露 LangGraph agent（agent.runtime.ask）给 HTTP 调用。
注意：本路由不复用 app.state.model_manager——agent.runtime 内部用 LLMmodel.create_minimax
显式创建 M3 实例，自给自足（与其他路由解耦）。
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent.runtime import ask

appagent = APIRouter()


class AgentRequest(BaseModel):
    """Agent 请求模型"""
    query: str = Field(..., description="用户问题")
    session_id: str | None = Field(None, description="会话 ID，不传则单轮")


class AgentResponse(BaseModel):
    """Agent 响应模型"""
    response: str = Field(..., description="agent 最终回答")


@appagent.post("/agent/chat", response_model=AgentResponse)
async def agent_chat(request: AgentRequest) -> AgentResponse:
    """Agent 入口：自动决定调 RAG 还是直接答。

    与 /chat 区别：/chat 是裸 LLM 直接答；/agent/chat 会经过 ReAct 循环 + 工具调用。
    """
    response = ask(request.query, request.session_id)
    return AgentResponse(response=response)
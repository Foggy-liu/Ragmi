# api/chat_api.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from .dependencies import get_rag_model
from core.rags.rags import RagModel

apprag = APIRouter()

class ChatRequest(BaseModel):
    """聊天请求模型"""
    query: str
    session_id: str = Field(None, description="会话 ID，不传则创建新对话")

class ChatResponse(BaseModel):
    """聊天响应模型"""
    response: str

@apprag.post("/rag", response_model=ChatResponse)
async def rag(
    request: ChatRequest,
    rag_model: RagModel = Depends(get_rag_model)
) -> ChatResponse:
    """聊天接口（RAG 模式）"""
    result = rag_model.chat(request.query, request.session_id)
    return ChatResponse(**result)

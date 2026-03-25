# api/chat_api.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from .dependencies import get_chat_model
from core.chat.chat import ChatModel

appchat = APIRouter()

class ChatRequest(BaseModel):
    """聊天请求模型"""
    query: str
    session_id: str = Field(None, description="会话ID，不传则创建新对话")

class ChatResponse(BaseModel):
    """聊天响应模型"""
    response: str

@appchat.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    chat_model: ChatModel = Depends(get_chat_model)
) -> ChatResponse:
    """聊天接口"""
    result = chat_model.chat(request.query, request.session_id)
    return ChatResponse(**result)
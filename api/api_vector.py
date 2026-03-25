# api/chat_api.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

appvector = APIRouter()

@appvector.post("/vector")
async def vector():
    """聊天接口"""
    return "OK"
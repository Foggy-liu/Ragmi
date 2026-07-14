from fastapi import Request,Depends
from core.chat.chat import ChatModel

def get_model_manager(request: Request):
    return request.app.state.model_manager

async def get_chat_model(
    model_manager = Depends(get_model_manager)
) -> ChatModel:
    return ChatModel(model_manager)


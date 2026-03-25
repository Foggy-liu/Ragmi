from fastapi import Request,Depends
from core.chat.chat import ChatModel

def get_model_manager(request: Request):
    return request.app.state.model_manager

async def get_chat_model(
    model_manager = Depends(get_model_manager)
) -> ChatModel:
    return ChatModel(model_manager)

# def get_something() -> SomeClass:  # ❌ 报错：SomeClass未定义
#     return something
#
# def create_something():
#     return SomeClass()
#
#
# def get_existing():
#     return existing_object  # ✅ 可以！existing_object已经在别处定义
#
# existing_object = {"name": "test"}  # 假设这个在别处
# get_existing()  # ✅ 正常运行
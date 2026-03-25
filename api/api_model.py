from fastapi import APIRouter,Request,Depends
from pydantic import BaseModel
from utils.models.model_manager import ModelManager
from .dependencies import get_model_manager

appmodel = APIRouter()

# 依赖项：获取模型管理器，通过这个导入依赖文件获取
# from .dependencies import get_model_manager


# 请求模型
class SwitchModelRequest(BaseModel):
    platform: str
    model_name: str


@appmodel.post("/switch_model")
# 模型切换路由
async def switch_model(
        request: SwitchModelRequest,
        model_manager=Depends(get_model_manager)
):
    """
    切换模型
    """
    success = model_manager.switch_model(request.platform, request.model_name)

    if success:
        current_model = model_manager.get_current_model()
        return {
            "success": True,
            "current_model": {
                "platform": current_model.platform,
                "model_name": current_model.model_name
            }
        }
    else:
        return {
            "success": False,
            "message": "模型切换失败"
        }


# 获取可用模型列表
@appmodel.get("/available")
async def get_available_models(
        model_manager=Depends(get_model_manager)
):
    available = model_manager.get_available_models()
    return {
        "available_models": [
            {"platform": p, "model_name": m}
            for p, m in available
        ]
    }

@appmodel.get("/current_model")
async def current_model(
        model_manager=Depends(get_model_manager)
):
    current = model_manager.get_current_model()
    return {
        "platform": current.platform,
        "model_name": current.model_name
    }
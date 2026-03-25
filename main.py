from fastapi import FastAPI,Request
from uvicorn import run

from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel

from api.api_chat import appchat
from api.api_model import appmodel
from api.api_rag import apprag

app = FastAPI()

# 创建管理器
model_manager = ModelManager()
model_manager.load_config_models()

# 创建默认模型并设置
default_model = LLMmodel.create_aliyun()
model_manager.set_current_model(default_model)  # 只是调用方法，不赋值

# 存入全局状态
app.state.model_manager = model_manager

app.include_router(appchat,tags=["chat"])
app.include_router(appmodel,tags=["model"])
app.include_router(apprag,tags=["rag"])


@app.get("/debug/simple")
async def debug_simple(request: Request):
    """简单查看"""
    # 修复：不能用.keys()，要用字典转换或hasattr
    result = {
        "app.state类型": type(request.app.state).__name__,
        "是否有model_manager": hasattr(request.app.state, 'model_manager')
    }

    if hasattr(request.app.state, 'model_manager'):
        mgr = request.app.state.model_manager
        result.update({
            "当前模型": f"{mgr.current_model.platform}-{mgr.current_model.model_name}" if mgr.current_model else "None",
            "可用模型数量": len(mgr.available_models),
            "已实例化模型": list(mgr.instantiated_models.keys())
        })

    return result


if __name__ == "__main__":
    run(app, host="127.0.0.1", port=8000)

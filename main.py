from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import run

from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel
from utils.logging import setup_logging

from api.api_chat import appchat
from api.api_model import appmodel
from api.api_rag import apprag
from api.api_agent import appagent
from api.api_file import app as appfile


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动期校验：UPLOAD_DIR 可写、Milvus 探活。"""
    setup_logging("INFO")

    upload_dir = Path("documents").resolve()
    if not upload_dir.exists():
        upload_dir.mkdir(parents=True, exist_ok=True)
        print(f"[lifespan] 创建上传目录: {upload_dir}")
    if not upload_dir.is_dir():
        raise RuntimeError(f"上传目录不可写: {upload_dir}")

    # Milvus 探活（不阻塞启动）
    try:
        from pymilvus import MilvusClient
        from utils.models.embedding_model import EmbeddingModel
        embed = EmbeddingModel.create_default()
        milvus_cfg = embed.get_milvus_config()
        client = MilvusClient(host=milvus_cfg["host"], port=milvus_cfg["port"])
        client.list_collections()
        print(f"[lifespan] Milvus 探活成功: {milvus_cfg['host']}:{milvus_cfg['port']}")
    except Exception as e:
        print(f"[lifespan] Milvus 探活失败（不阻塞启动）: {e}")

    yield


app = FastAPI(lifespan=lifespan)

# 开发期 CORS：允许任意 origin（浏览器 dashboard 测试用）
# 生产部署应改为白名单（前端域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建管理器
model_manager = ModelManager()
model_manager.load_config_models()

# 创建默认模型并设置
default_model = LLMmodel.create_minimax()
model_manager.set_current_model(default_model)  # 只是调用方法，不赋值

# 存入全局状态
app.state.model_manager = model_manager

app.include_router(appchat, tags=["chat"])
app.include_router(appmodel, tags=["model"])
app.include_router(apprag, tags=["rag"])
app.include_router(appagent, tags=["agent"])
app.mount("/api", appfile, name="file")


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

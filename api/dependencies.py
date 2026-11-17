"""api/dependencies.py —— 依赖注入的统一入口。

为什么要有这个文件：
1. **不重复** —— 每个路由都写一遍 `request.app.state.model_manager` 是重复代码；
2. **单一事实来源** —— "共享状态从哪拿"只在这里定义一处；
3. **可测试** —— `app.dependency_overrides[get_chat_model] = ...` 给测试一个
   替换点，不用碰真实模型。

⚠️ FastAPI 的 `Depends` 缓存**只在单个请求内有效**（`use_cache=True` 的意思是
"这次请求里依赖被调几次都只算一次"），**跨请求不复用**。
所以「便宜」的依赖（ChatModel 只是存一下 model_manager）每次请求现建没问题，
「贵」的依赖（RagModel 要建 embedding HTTP 客户端 + 读配置 + 探活）必须自己做成 app 级单例。
"""
from threading import Lock

from fastapi import Depends, Request

from core.chat.chat import ChatModel
from core.rags.rags import RagModel


def get_model_manager(request: Request):
    """拿到全局的 ModelManager（main.py 启动时创建，进程内唯一）。"""
    return request.app.state.model_manager


async def get_chat_model(
    model_manager=Depends(get_model_manager)
) -> ChatModel:
    """ChatModel 很轻（只存 model_manager）—— 每个请求建一个无所谓。"""
    return ChatModel(model_manager)


# 建 RagModel 时用的锁：并发首请求只建一个，不建两遍
_rag_model_lock = Lock()


def get_rag_model(request: Request) -> RagModel:
    """RAG 模型 —— **app 级单例**（挂在 app.state 上）。

    为什么不能每次请求现建（实测拆解，2026-11-17）：
    - `RagModel.__init__` ~0.45s，其中 **~0.42s 是建 embedding HTTP 客户端**
      （`OllamaEmbeddings` 会建同步+异步**两个** httpx 客户端，每个都要建一次
      SSL 上下文 → 读 CA 证书包），另外是读 YAML + `load_dotenv` + 两次健康检查 RPC；
    - 而一次真正的检索只要 **~0.10s** —— 也就是说每请求 **~82% 的时间在做重复的准备**；
    - 并发请求会把这个开销线性放大（每个请求各建一套客户端、各读一遍配置）。

    ⚠️ 注意：**不是**"每请求重开一条 Milvus gRPC 连接" —— pymilvus 2.6 自带
    `ConnectionManager`，按地址缓存底层 gRPC 通道，第二个客户端起就是 0.000s 复用。

    连接失败（Milvus 没起）时**不缓存** —— 否则启动期的一次抖动会让这个进程
    永远检索不了；下次请求会重新建、重新连。
    """
    state = request.app.state

    rag_model = getattr(state, "rag_model", None)
    if rag_model is not None:
        return rag_model

    with _rag_model_lock:
        # 双检：等锁期间可能已经被别的请求建好了
        rag_model = getattr(state, "rag_model", None)
        if rag_model is None:
            rag_model = RagModel(state.model_manager)
            if rag_model.is_ready:
                state.rag_model = rag_model
    return rag_model

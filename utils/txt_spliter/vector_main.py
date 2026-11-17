from pymilvus import MilvusClient, DataType
from utils.models.embedding_model import EmbeddingModel
from utils.txt_spliter import spliter
from dotenv import load_dotenv
import os
import time
import requests

# 直连 Ollama HTTP API（不走 langchain_ollama 库 —— 该库在本机会被代理到错误端口）
#
# ⚠️ 嵌入模型名 / base_url **不能在模块导入时读环境变量**：
# 导入那一刻 .env 还没被 load_dotenv() 加载 → .env 里的 EMBEDDING_MODEL /
# OLLAMA_BASE_URL 会被静默忽略（P3-9）。
# 真正的解析放在 resolve_embed_settings()，且必须在 EmbeddingModel 构造**之后**
# 调用（它的 __init__ 里会 load_dotenv）。
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
EMBED_BATCH_SIZE = 32  # 单次 /api/embed 请求的文档上限


def resolve_embed_settings(embed_model):
    """返回 (model_name, base_url) —— 索引端与检索端共用的**唯一事实来源**。

    优先级：环境变量 > YAML（``configs/model_config.yaml``）。
    embed_model 必须已经构造好 —— 它的 ``__init__`` 里会 load_dotenv。

    ⚠️ 两端模型名不一致时 Milvus **不会报错**（维度一样的话），
    只会让检索结果全是噪声 —— 所以两边必须从这里取同一个值（P1-9）。
    """
    model = os.environ.get("EMBEDDING_MODEL") or embed_model.model_name
    base_url = (
        os.environ.get("OLLAMA_BASE_URL")
        or embed_model.platform_config.get("api_base_url")
        or DEFAULT_OLLAMA_BASE_URL
    )
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return model, base_url


def ollama_embed_texts(texts, model, base_url, batch_size=EMBED_BATCH_SIZE):
    """分批调用 Ollama /api/embed，返回 list[list[float]]。

    为什么不用 langchain_ollama.OllamaEmbeddings：本机 ollama 库版本
    在批量 embed 时会走一个 52266/53814 等高位随机端口 + /tokenize 端点，
    那是某个 HTTP 代理/服务网格的拦截口而不是真正的 Ollama（11434）。
    直连 11434 + /api/embed 才是规范的 Ollama HTTP API。
    """
    all_vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = requests.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": batch},
            timeout=60,
        )
        resp.raise_for_status()
        all_vectors.extend(resp.json()["embeddings"])
    return all_vectors


def ollama_embed_one(text, model, base_url):
    """单条文本 embed（用于探测维度）。"""
    return ollama_embed_texts([text], model=model, base_url=base_url)[0]


def vector_split():
    # 1、初始化embedding管理类
    embed_model = EmbeddingModel.create_default()

    # 1.5、解析嵌入模型名 / base_url（必须在 EmbeddingModel 构造之后 —— 它才会 load_dotenv）
    embed_model_name, ollama_base_url = resolve_embed_settings(embed_model)
    print(f"使用嵌入模型: {embed_model_name} @ {ollama_base_url}")

    # 2、初始化切分器
    splitter = spliter.Splitter()

    # 3、切分文件（处理 txt/ 目录下所有文件）
    documents = splitter.split_all_files()

    if not documents:
        print("未找到任何文档，请先在 txt/ 目录下放置文本文件")
        return None

    # 4、从配置文件中获取 Milvus 配置
    milvus_config = embed_model.get_milvus_config()

    # 5、（已移除 OllamaEmbeddings，改用 ollama_embed_one/ollama_embed_texts 直连 HTTP API）

    # 6、连接 Milvus
    client = MilvusClient(uri=f"http://{milvus_config.get('host', '127.0.0.1')}:{milvus_config.get('port', '19530')}")

    alias_name = milvus_config.get('collection_name', 'txt_data')  # alias 名称固定为配置中的 collection_name
    new_collection_name = f"{alias_name}_{int(time.time())}"  # 实际集合名带时间戳

    print(f"将创建新集合: {new_collection_name}，alias '{alias_name}' 将指向新集合")

    # 8、获取一个 embedding 来确定维度
    sample_text = documents[0].page_content
    sample_embedding = ollama_embed_one(sample_text[:50], embed_model_name, ollama_base_url)
    dim = len(sample_embedding)
    print(f"Embedding 维度: {dim}")

    # 9、创建 schema
    schema = client.create_schema(enable_dynamic_field=True)
    schema.add_field(field_name='id', datatype=DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field(field_name='vector', datatype=DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field(field_name='text', datatype=DataType.VARCHAR, max_length=65535)

    # 10、创建新集合（实际名带时间戳，不是 alias 名）
    client.create_collection(collection_name=new_collection_name, schema=schema)
    print(f"创建新集合: {new_collection_name}")

    # 11、为每个文档生成 embedding 并插入
    all_texts = [doc.page_content for doc in documents]
    print(f"正在为 {len(all_texts)} 个文档片段生成 embedding...")

    vectors = ollama_embed_texts(all_texts, embed_model_name, ollama_base_url)
    print(f"生成 {len(vectors)} 个向量")

    # 12、批量插入（分批避免内存问题）
    batch_size = 100
    total_inserted = 0

    for i in range(0, len(documents), batch_size):
        batch_end = min(i + batch_size, len(documents))
        batch_vectors = vectors[i:batch_end]
        batch_texts = all_texts[i:batch_end]

        entities = [{'vector': batch_vectors[j], 'text': batch_texts[j]} for j in range(len(batch_texts))]

        result = client.insert(collection_name=new_collection_name, data=entities)
        total_inserted += result['insert_count']
        print(f"已插入 {total_inserted}/{len(documents)} 个片段")

    print(f"共插入 {total_inserted} 个文档片段")

    # 13、创建索引
    print("正在创建索引...")
    index_params = client.prepare_index_params(field_name='vector', index_type='AUTOINDEX', metric_type='COSINE')
    client.create_index(collection_name=new_collection_name, index_params=index_params)

    # 14、加载 collection
    print("正在加载集合...")
    client.load_collection(collection_name=new_collection_name)

    # 15、原子切换 alias（核心：旧集合不删，新集合接替）
    try:
        # 检查 alias 是否已存在
        client.describe_alias(alias_name)
        alias_exists = True
    except Exception:
        alias_exists = False

    if alias_exists:
        # 已有 alias：用 alter_alias 原子切换（旧集合保留，回滚窗口由人工清理）
        client.alter_alias(new_collection_name, alias_name)
        print(f"已原子切换 alias '{alias_name}' -> 新集合 '{new_collection_name}'")
        print(f"旧集合（如有）保留 7 天，可在 Milvus 控制台手动删除")
    else:
        # 首次：直接创建 alias
        client.create_alias(new_collection_name, alias_name)
        print(f"已创建 alias '{alias_name}' -> 新集合 '{new_collection_name}'")

    print(f"Milvus 向量库创建成功！")
    print(f"Alias 名称: {alias_name} (指向 {new_collection_name})")
    print(f"文档片段数: {total_inserted}")

    return client


if __name__ == '__main__':
    vector_split()

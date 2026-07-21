from langchain_ollama import OllamaEmbeddings
from pymilvus import MilvusClient, DataType
from utils.models.embedding_model import EmbeddingModel
from utils.txt_spliter import spliter
from dotenv import load_dotenv
import os
import time


def vector_split():
    # 1、初始化embedding管理类
    embed_model = EmbeddingModel.create_default()

    # 2、初始化切分器
    splitter = spliter.Spliter()

    # 3、切分文件（处理 txt/ 目录下所有文件）
    documents = splitter.split_all_files()

    if not documents:
        print("未找到任何文档，请先在 txt/ 目录下放置文本文件")
        return None

    # 4、从配置文件中获取 Milvus 配置
    milvus_config = embed_model.get_milvus_config()

    # 5、获取 embedding 函数（bge-large）
    embed = OllamaEmbeddings(model='bge-large', base_url='http://localhost:11434')

    # 6、连接 Milvus
    client = MilvusClient(uri=f"http://{milvus_config.get('host', '127.0.0.1')}:{milvus_config.get('port', '19530')}")

    alias_name = milvus_config.get('collection_name', 'txt_data')  # alias 名称固定为配置中的 collection_name
    new_collection_name = f"{alias_name}_{int(time.time())}"  # 实际集合名带时间戳

    print(f"将创建新集合: {new_collection_name}，alias '{alias_name}' 将指向新集合")

    # 8、获取一个 embedding 来确定维度
    sample_text = documents[0].page_content
    sample_embedding = embed.embed_query(sample_text[:50])
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

    vectors = embed.embed_documents(all_texts)
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

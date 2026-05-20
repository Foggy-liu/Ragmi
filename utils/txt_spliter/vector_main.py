from langchain_ollama import OllamaEmbeddings
from langchain_milvus import Milvus
from utils.models.embedding_model import EmbeddingModel
from utils.txt_spliter import spliter
from dotenv import load_dotenv
import os


def vector_split():
    # 1、初始化embedding管理类
    embed_model = EmbeddingModel.create_default()

    # 2、初始化切分器
    splitter = spliter.Splitter()

    # 3、切分文件（处理 txt/ 目录下所有文件）
    documents = splitter.split_all_files()

    # 4、从配置文件中获取 Milvus 配置
    milvus_config = embed_model.get_milvus_config()

    # 5、创建 Milvus 向量数据库实例
    vector_store = Milvus.from_documents(
        documents=documents,  # 传 Document 对象
        embedding=embed_model.embedding,  # Milvus 用这个模型做向量化
        collection_name=milvus_config.get("collection_name", "txt_data"),
        connection_args={
            "host": milvus_config.get("host", "127.0.0.1"),
            "port": milvus_config.get("port", "19530"),
        },
        drop_old=False,  # 不覆盖已有数据，支持增量
    )

    print(f"Milvus 向量库创建成功！")
    print(f"集合名称: {milvus_config.get('collection_name', 'txt_data')}")
    print(f"文档片段数: {len(documents)}")

    return vector_store


if __name__ == '__main__':
    vector_split()
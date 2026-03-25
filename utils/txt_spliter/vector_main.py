from langchain_chroma import Chroma
from utils.models.embedding_model import EmbeddingModel
from utils.txt_spliter import spliter


def vector_split():

    # 1、初始化embedding管理类
    embed_model = EmbeddingModel.create_default()

    # 2、初始化切分器
    splitter = spliter.Splitter()

    # 3、切分文件
    documents = splitter.split_all_files()

    # documents = splitter.split_file('../../txt/01_RAG_intro_md.txt')

    # 4、从配置文件中获取向量数据库的配置
    vector_config = embed_model.get_vector_store_config()

    # 5、创建向量数据库示例对象
    vector_store = Chroma.from_documents(
        documents=documents,  # 传Document对象
        embedding=embed_model.embedding,  # Chroma会用这个模型
        persist_directory=vector_config["persist_directory"]  # 数据存储目录位置，从配置文件中读取
    )

    # embeddings = embed_model.embed_documents(documents[0].page_content)    # 使用embedding，向量化document里面的内容
    # texts = [doc.page_content for doc in documents]  # 只提取所有documents的文本部分
    # print(vector_config)

    print(f"向量库创建成功！")
    print(f"存储位置: {vector_config['persist_directory']}")
    print(f"文档片段数: {len(documents)}")

    return vector_store


if __name__ == '__main__':
    vector_split()








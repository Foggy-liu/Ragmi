# """
# RAG 对话
# """
# from utils.message.message import MessageManager
# from typing import Dict, List, Optional
#
# from utils.models.embedding_model import EmbeddingModel
#
# # 创建全局的单例 MessageManager
# _global_msg_manager = MessageManager()
#
# class RagModel:
#     def __init__(self, model_manager):
#         self.model_manager = model_manager
#         # self.msg_manager = MessageManager()
#         # 使用全局的 MessageManager，而不是每次创建新的
#         self.msg_manager = _global_msg_manager
#
#     def chat(self, query: str, session_id: str = None) -> Dict[str, str]:
#         """主业务：输入字符串，输出字符串"""
#         # 1. 会话管理
#         session_id = self.msg_manager.ensure_session(session_id)
#
#         # 2. 构造消息体
#         custom_system = """你是一个专业的个人知识库问答助手，基于提供的相关文档片段回答问题。
#
#         请严格按照以下规则执行：
#         1. 仔细分析用户的问题，明确需要的信息类型
#         2. 严格基于提供的【相关文档】内容回答问题，不要使用外部知识
#         3. 如果【相关文档】中包含足够信息，请直接、清晰地回答用户问题
#         4. 如果【相关文档】中的信息不完整或与问题不完全相关，回答时请注明：
#            - 根据提供的文档，可以回答的部分内容是什么
#            - 文档中缺失的信息是什么
#         5. 如果【相关文档】完全不包含相关信息，请明确告知："根据提供的知识库，无法回答这个问题。"
#         6. 如果问题模糊或不清晰，请询问具体需要了解什么内容
#         7. 保持回答的专业性和准确性，重要信息可以引用文档中的关键点
#         8. 回答格式：先直接回答问题，然后简要说明回答的依据
#
#         注意：每次回答前，请确保已充分考虑【相关文档】中的全部相关内容。"""
#         messages = self.msg_manager.build_messages(session_id, query,custom_system)
#
#         # 3. 文本切分并文本向量化（这部分应该已经完成了），现在需要获取嵌入模型，将用户的提问向量化
#         embed_model = EmbeddingModel.create_default()
#         query_embedding = embed_model.embed_query(query)
#
#         # 4. 获取向量数据库，向量相似度搜索，获取向量数据库这一步并不是在创建向量数据库函数实现的过程中来使用创建的数据库实例，而是通过目录获取
#
#
#
#
#
#
#
#
#
#         # 3. 调用模型
#         model = self.model_manager.get_current_model()
#         response = model.invoke(messages)
#
#         # 4. 保存历史
#         self.msg_manager.add_to_history(session_id, query, response)
#
#         # 5. 返回字符串
#         return {"response": response}
#
#
#
from utils.message.message import MessageManager
from typing import Dict, List, Optional
from langchain_chroma import Chroma
from utils.models.embedding_model import EmbeddingModel
import os

# 创建全局的单例 MessageManager
_global_msg_manager = MessageManager()


class RagModel:
    def __init__(self, model_manager):
        self.model_manager = model_manager
        # 使用全局的 MessageManager，而不是每次创建新的
        self.msg_manager = _global_msg_manager
        # 初始化向量数据库（全局读取一次）
        self.vector_store = self._load_vector_store()

    def _load_vector_store(self):
        """
        从磁盘加载已存在的向量数据库
        只在初始化时执行一次
        """
        # 1. 初始化embedding模型
        embed_model = EmbeddingModel.create_default()

        # 2. 从配置文件中获取向量数据库的存储路径
        vector_config = embed_model.get_vector_store_config()
        persist_dir = vector_config["persist_directory"]

        # 3. 检查向量库是否存在
        if not os.path.exists(persist_dir):
            print(f"警告：向量库不存在于 {persist_dir}")
            print("请先运行 vector_main.py 创建向量库")
            return None

        try:
            # 4. 加载已存在的向量库
            vector_store = Chroma(
                persist_directory=persist_dir,
                embedding_function=embed_model.embedding
            )
            # 获取文档数量（可选，用于验证）
            doc_count = vector_store._collection.count()
            print(f"成功加载向量库：{persist_dir}")
            print(f"包含 {doc_count} 个文档片段")
            return vector_store
        except Exception as e:
            print(f"加载向量库失败：{e}")
            return None

    def _search_similar_chunks(self, query: str, top_k: int = 5) -> List[str]:
        """
        向量相似度搜索
        每次用户提问时执行
        """
        # 1. 检查向量库是否已加载
        if not self.vector_store:
            print("向量库未加载，无法进行相似度搜索")
            return []

        try:
            # 2. 执行相似度搜索
            docs = self.vector_store.similarity_search(query, k=top_k)

            # 3. 提取文档内容
            chunks = [doc.page_content for doc in docs]

            # 可选：打印检索到的文档信息（用于调试）
            # for i, doc in enumerate(docs):
            #     source = doc.metadata.get('source', '未知来源')
            #     print(f"检索到第{i+1}个片段：来自{source}")

            return chunks
        except Exception as e:
            print(f"相似度搜索失败：{e}")
            return []

    def _build_context_prompt(self, query: str, relevant_chunks: List[str]) -> str:
        """
        构建包含上下文的提示词
        """
        # 如果没有检索到相关文档
        if not relevant_chunks:
            context = "没有找到相关文档片段。"
        else:
            # 将多个文档片段合并为上下文
            context = "\n\n---\n\n".join(relevant_chunks)

        # 构建完整的提示词
        custom_system = f"""你是一个基于RAG的个人知识库问答助手。

        身份：当被问你是谁，回答“我是个人知识库问答助手”。

        规则：
        - 严格基于以下文档回答
        - 文档无信息则告知无法回答
        - 用户追问“依据”时再引用文档

        文档：{context}

        问题：{query}"""

        return custom_system

    def chat(self, query: str, session_id: str = None) -> Dict[str, str]:
        """主业务：输入字符串，输出字符串"""
        # 1. 会话管理
        session_id = self.msg_manager.ensure_session(session_id)

        # 2. 向量相似度搜索（每次对话执行）
        relevant_chunks = self._search_similar_chunks(query, top_k=5)

        # 3. 构建带上下文的提示词
        custom_system = self._build_context_prompt(query, relevant_chunks)

        # 4. 构造消息体
        messages = self.msg_manager.build_messages(session_id, query, custom_system)

        # 5. 调用模型
        model = self.model_manager.get_current_model()
        response = model.invoke(messages)

        # 6. 保存历史
        self.msg_manager.add_to_history(session_id, query, response)

        # 7. 返回字符串
        return {"response": response}
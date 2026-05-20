"""
RAG 对话
"""
from utils.message.message import MessageManager
from typing import Dict, List, Optional
from langchain_milvus import Milvus
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
        从 Milvus 加载已存在的向量数据库
        只在初始化时执行一次
        """
        # 1. 初始化embedding模型
        embed_model = EmbeddingModel.create_default()

        # 2. 获取 Milvus 连接配置
        milvus_config = embed_model.get_milvus_config()

        try:
            # 3. 连接到 Milvus 向量数据库
            vector_store = Milvus(
                embedding_function=embed_model.embedding,
                collection_name=milvus_config.get("collection_name", "txt_data"),
                connection_args={
                    "host": milvus_config.get("host", "127.0.0.1"),
                    "port": milvus_config.get("port", "19530"),
                },
                drop_old=False,  # 不删除已有集合
            )

            print(f"成功连接 Milvus 向量库")
            print(f"集合名称: {milvus_config.get('collection_name', 'txt_data')}")
            return vector_store
        except Exception as e:
            print(f"连接 Milvus 向量库失败：{e}")
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

        身份：当被问你是谁，回答"我是RAGMI"。

        规则：
        - 严格基于以下文档回答
        - 文档无信息则告知无法回答
        - 用户追问"依据"时再引用文档

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
"""
RAG 对话
"""


class ConfigError(Exception):
    """配置错误，启动期应 fail-fast。"""
    pass


from utils.message.message import MessageManager
from typing import Dict, List, Optional
from pymilvus import MilvusClient
from langchain_ollama import OllamaEmbeddings
from utils.models.embedding_model import EmbeddingModel
from utils.logging import get_logger
import os

logger = get_logger(__name__)

# 创建全局的单例 MessageManager
_global_msg_manager = MessageManager()


class RagModel:
    def __init__(self, model_manager):
        self.model_manager = model_manager
        # 使用全局的 MessageManager，而不是每次创建新的
        self.msg_manager = _global_msg_manager
        # 初始化向量数据库（全局读取一次）
        self._client = None
        self._embed = None
        self._collection_name = None
        self._load_vector_store()

    def _load_vector_store(self):
        """
        从 Milvus 加载已存在的向量数据库
        只在初始化时执行一次
        """
        try:
            # 1. 初始化embedding模型
            embed_model = EmbeddingModel.create_default()

            # 2. 获取 Milvus 连接配置
            milvus_config = embed_model.get_milvus_config()

            # 3. 初始化 Ollama embedding
            self._embed = OllamaEmbeddings(model='bge-large', base_url='http://localhost:11434')

            # 4. 连接到 Milvus（缺字段立刻报错，不掩盖）
            try:
                host = milvus_config['host']
                port = milvus_config['port']
            except KeyError as e:
                raise ConfigError(
                    f"Milvus 配置缺失字段 {e}，请检查 configs/model_config.yaml 的 "
                    "EMBEDDING_CONFIG.vector_store.milvus 节"
                ) from e
            self._client = MilvusClient(uri=f"http://{host}:{port}")

            # 5. 获取集合名称（缺字段立刻报错）
            try:
                self._collection_name = milvus_config['collection_name']
            except KeyError as e:
                raise ConfigError(
                    f"Milvus 配置缺失 collection_name 字段，请检查 "
                    "configs/model_config.yaml"
                ) from e

            # 6. 检查集合是否存在
            if not self._client.has_collection(self._collection_name):
                logger.warning(f"集合 {self._collection_name} 不存在，请先运行 vector_main.py")
                self._client = None
                return

            # 7. 确保集合已加载
            load_state = self._client.get_load_state(collection_name=self._collection_name)
            if load_state['state'] != 'Loaded':
                self._client.load_collection(collection_name=self._collection_name)

            logger.info(f"成功连接 Milvus 向量库")
            logger.info(f"集合名称: {self._collection_name}")

        except Exception as e:
            logger.exception(f"连接 Milvus 向量库失败：{e}")
            self._client = None

    def _search_similar_chunks(self, query: str, top_k: int = 5) -> List[str]:
        """
        向量相似度搜索
        每次用户提问时执行
        """
        # 1. 检查向量库是否已加载
        if not self._client:
            logger.warning("向量库未加载，无法进行相似度搜索")
            return []

        try:
            # 2. 将查询文本转为向量
            query_vector = self._embed.embed_query(query)

            # 3. 执行相似度搜索
            results = self._client.search(
                collection_name=self._collection_name,
                data=[query_vector],
                limit=top_k,
                output_fields=['text']
            )

            # 4. 提取文档内容
            chunks = []
            for hit in results[0]:
                chunks.append(hit.entity.get('text', ''))

            return chunks
        except Exception as e:
            logger.exception(f"相似度搜索失败：{e}")
            return []

    def retrieve(self, query: str, top_k: int = 5) -> List[str]:
        """公开检索入口：只返回 chunks，不调 LLM。

        给 agent 当工具用：方案 2（1-LLM 路径）。
        内部可演进——未来加重排 / 混合检索时，只改这个方法体，
        agent 工具代码 0 改动。
        """
        return self._search_similar_chunks(query, top_k)

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
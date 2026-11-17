from langchain_ollama import OllamaEmbeddings
from langchain_milvus import Milvus
from dotenv import load_dotenv
import os
import yaml
from pathlib import Path
from typing import List


# YAML 里 ${VAR} 占位符在环境变量缺失时的兜底。
# 没有它，缺失变量会把字面量 "${OLLAMA_BASE_URL}" 当成 base_url 用 → 一个看不懂的 URL 错误。
_ENV_FALLBACKS = {"OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1"}


class EmbeddingModel:
    def __init__(self, platform=None, model_name=None, **kwargs):
        current_script_path = Path(__file__).resolve()
        self.ROOT_DIR = current_script_path.parent.parent.parent

        load_dotenv(self.ROOT_DIR / ".env", override=True)

        llm_root = os.environ.get("LLM_ROOT", "../..")
        self.ROOT_DIR = Path(llm_root).resolve()
        load_dotenv(self.ROOT_DIR / ".env", override=True)

        self.CONFIG_PATH = self.ROOT_DIR / "configs" / "model_config.yaml"

        with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
            self.yaml_config = yaml.safe_load(f)

        self.platform = platform or self.yaml_config["DEFAULT_EMBEDDING_MODEL"]["platform"]
        self.model_name = model_name or self._resolve_model_name()

        self.platform_config = self._get_platform_config()
        self.model_defaults = self._get_model_defaults()

        params = self._merge_params(kwargs)
        self.embedding = self._init_client(params)

    def _resolve_model_name(self) -> str:
        """嵌入模型名的**唯一事实来源**。

        优先级：环境变量 ``EMBEDDING_MODEL`` > YAML ``DEFAULT_EMBEDDING_MODEL.model_name``。

        ⚠️ 索引端（``utils/txt_spliter/vector_main.py``）和检索端
        （``core/rags/rags.py``）必须用**同一个**模型名 ——
        向量空间对不上时 Milvus **不报错**（维度一样的话），只是检索结果全是噪声。
        以前检索端硬编码 ``model='bge-large'``、索引端读环境变量，两边可以静默分叉。
        """
        env_name = os.environ.get("EMBEDDING_MODEL")
        if env_name:
            return env_name
        return self.yaml_config["DEFAULT_EMBEDDING_MODEL"]["model_name"]

    def _get_platform_config(self):
        for plat in self.yaml_config.get("PLATFORMS", []):
            if plat.get("platform_name") == self.platform:
                for k, v in plat.items():
                    if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                        env_key = v.strip("${}")
                        plat[k] = os.getenv(env_key) or _ENV_FALLBACKS.get(env_key, v)
                return plat
        raise ValueError(f"平台{self.platform}未配置")

    def _get_model_defaults(self):
        try:
            return self.yaml_config["MODEL_DEFAULTS"]["ollama"]["embedding"][self.model_name]
        except KeyError:
            return {"dimensions": 1024, "context_size": 512}

    def _merge_params(self, kwargs):
        base_params = {
            "api_key": self.platform_config.get("api_key", ""),
            "base_url": self.platform_config.get("api_base_url", ""),
            "timeout": self.platform_config.get("timeout", 30),
            "model": self.model_name
        }
        base_params.update(self.model_defaults)
        base_params.update(kwargs)
        return base_params

    def _init_client(self, params):
        if self.platform == "ollama":
            base_url = params.get("base_url", "http://localhost:11434")
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]
            # ⚠️ OllamaEmbeddings 没有 timeout 字段，但 client_kwargs 会透传给
            # ollama.Client → httpx → 真正给到底层连接一个上限（P2-8）。
            # 以前 timeout 在 _merge_params 里算出来了却被这里丢掉 → 连接无界。
            timeout = params.get("timeout")
            client_kwargs = {"timeout": timeout} if timeout else {}
            return OllamaEmbeddings(
                model=self.model_name,
                base_url=base_url,
                client_kwargs=client_kwargs,
            )
        else:
            raise ValueError(f"不支持的平台: {self.platform}")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embedding.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.embedding.embed_query(text)

    def get_vector_store_config(self):
        embed_config = self.yaml_config.get("EMBEDDING_CONFIG", {})
        vector_config = embed_config.get("vector_store", {}).copy()

        if "persist_directory" in vector_config:
            path = vector_config["persist_directory"]
            if isinstance(path, str) and path.startswith("${") and path.endswith("}"):
                env_key = path[2:-1]
                vector_config["persist_directory"] = os.getenv(env_key, path)

        return vector_config

    def get_milvus_config(self):
        """获取 Milvus 连接配置（从 vector_store.milvus 读取，缺字段 fail-loud）。"""
        embed_config = self.yaml_config.get("EMBEDDING_CONFIG", {})
        vector_store = embed_config.get("vector_store", {})
        milvus_config = vector_store.get("milvus", {}).copy()

        if not milvus_config:
            raise ValueError(
                "EMBEDDING_CONFIG.vector_store.milvus 配置缺失或为空，"
                "请检查 configs/model_config.yaml"
            )

        # 从环境变量替换占位符
        for k, v in milvus_config.items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                env_key = v[2:-1]
                milvus_config[k] = os.getenv(env_key, v)

        return milvus_config

    @staticmethod
    def create_default():
        return EmbeddingModel()


if __name__ == '__main__':
    embed_model = EmbeddingModel.create_default()
    print(f"嵌入模型初始化成功: {embed_model.platform}/{embed_model.model_name}")

    test_texts = ["这是一个测试文档", "这是另一个测试文档"]
    embeddings = embed_model.embed_documents(test_texts)
    print(f"生成的向量维度: {len(embeddings[0]) if embeddings else 0}")

    vector_config = embed_model.get_vector_store_config()
    print(f"向量数据库配置: {vector_config}")
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import yaml
from pathlib import Path

# YAML 里 ${VAR} 占位符在环境变量缺失时的兜底（见 embedding_model.py 同名常量）
_ENV_FALLBACKS = {"OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1"}


class LLMmodel:
    def __init__(self, platform=None, model_name=None, **kwargs):
        current_script_path = Path(__file__).resolve()
        # 向上两级找到项目根目录（model_setting.py在bankcend/model/下，根目录是newchat）
        self.ROOT_DIR = current_script_path.parent.parent.parent  # 对应路径：bankcend/model/ → bankcend/ → newchat/

        # 加载根目录下的.env
        load_dotenv(self.ROOT_DIR / ".env", override=True)

        # 第二步：从.env/系统环境变量读LLM_ROOT，无则用当前目录兜底
        llm_root = os.environ.get("LLM_ROOT", "../..")  # 兜底当前目录
        self.ROOT_DIR = Path(llm_root).resolve()  # 解析为绝对路径

        # 第三步：重新加载「根目录下」的.env（确保加载的是正确的.env）
        load_dotenv(self.ROOT_DIR / ".env", override=True)  # override=True覆盖已加载的

        # 后续路径拼接逻辑不变（基于ROOT_DIR）
        self.CONFIG_PATH = self.ROOT_DIR / "configs" / "model_config.yaml"
        self.ENV_PATH = self.ROOT_DIR / ".env"

        # 以下逻辑完全不变
        self.yaml_config = self._load_yaml()
        self.platform = platform or self.yaml_config["DEFAULT_MODEL"]["platform"]
        self.model_name = model_name or self.yaml_config["DEFAULT_MODEL"]["model_name"]

        self.platform_config = self._get_platform_config()
        self.model_defaults = self._get_model_defaults()
        final_params = self._merge_params(kwargs)
        self.chat = self._init_client(final_params)

    # 其余函数（_load_yaml/_get_platform_config等）完全不变
    def _load_yaml(self):
        """加载YAML配置文件"""
        if not self.CONFIG_PATH.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.CONFIG_PATH}")
        try:
            with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RuntimeError(f"YAML配置解析失败: {str(e)}")

    def _get_platform_config(self):
        """获取指定平台的配置（替换.env占位符）"""
        for plat in self.yaml_config.get("PLATFORMS", []):
            if plat.get("platform_name") == self.platform:
                for k, v in plat.items():
                    if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                        env_key = v.strip("${}")
                        plat[k] = os.getenv(env_key) or _ENV_FALLBACKS.get(env_key, v)
                return plat
        raise ValueError(f"平台{self.platform}未配置，请检查model_config.yaml")

    def _get_model_defaults(self):
        """获取模型默认参数，无配置时返回兜底值"""
        try:
            return self.yaml_config["MODEL_DEFAULTS"][self.platform][self.model_name]
        except KeyError:
            print(f"警告: {self.platform}-{self.model_name}无默认参数，使用基础配置")
            return {"temperature": 0.7, "max_tokens": 4096, "history_len": 10}

    def _merge_params(self, kwargs):
        """合并参数：自定义参数>模型默认>平台默认"""
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
        """初始化ChatOpenAI客户端（过滤无效参数）"""
        valid_keys = ["api_key", "base_url", "model", "temperature", "max_tokens", "timeout"]
        valid_params = {k: v for k, v in params.items() if k in valid_keys}
        try:
            return ChatOpenAI(**valid_params)
        except Exception as e:
            raise RuntimeError(f"客户端初始化失败: {str(e)}")

    def invoke(self, messages):
        """调用模型生成回复，返回文本内容"""
        try:
            response = self.chat.invoke(messages)
            return response.content
        except Exception as e:
            raise RuntimeError(f"模型调用失败: {str(e)}")

    @staticmethod
    def create_ollama(model_name="deepseek-r1:1.5b", **kwargs):
        """快速创建ollama平台模型实例"""
        return LLMmodel(platform="ollama", model_name=model_name, **kwargs)

    @staticmethod
    def create_aliyun(model_name="qwen3.5-plus", **kwargs):
        """快速创建阿里云平台模型实例"""
        return LLMmodel(platform="aliyun", model_name=model_name, **kwargs)

    @staticmethod
    def create_minimax(model_name="MiniMax-M3.1-Flash", **kwargs):
        """快速创建minimax平台模型实例（默认 MiniMax-M3.1-Flash）"""
        return LLMmodel(platform="minimax", model_name=model_name, **kwargs)

    # @staticmethod
    # def create_openai(model_name="gpt-3.5-turbo", **kwargs):
    #     """快速创建openai平台模型实例"""
    #     return MultiPlatformLLM(platform="openai", model_name=model_name, **kwargs)

if __name__ == '__main__':
    try:
        model = LLMmodel.create_aliyun()
        print(model.invoke([{"role": "user", "content": "你好"}]))
    except Exception as e:
        print(f"执行失败: {str(e)}")
from typing import Dict, List, Tuple, Optional
import yaml
from pathlib import Path
from utils.models.model_setting import LLMmodel


class ModelManager:
    def __init__(self):
        self.available_models: List[Tuple[str, str]] = []  # (平台, 模型名)
        self.instantiated_models: Dict[str, 'LLMmodel'] = {}  # key: "platform::model_name"
        self.current_model: Optional['LLMmodel'] = None
        self.current_model_key: str = ""

    def _get_model_key(self, platform: str, model_name: str) -> str:
        return f"{platform}::{model_name}"

    def load_config_models(self, config_path: Path = None):
        """
        加载模型列表
        :param config_path:
        :return:
        """
        if config_path is None:
            current_script_path = Path(__file__).resolve()
            ROOT_DIR = current_script_path.parent.parent.parent
            config_path = ROOT_DIR / "configs" / "model_config.yaml"

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.available_models.clear()

        for platform_config in config.get("PLATFORMS", []):
            platform = platform_config.get("platform_name")
            if not platform:
                continue

            model_defaults = config.get("MODEL_DEFAULTS", {}).get(platform, {})
            for model_name in model_defaults.keys():
                self.available_models.append((platform, model_name))

        default_config = config.get("DEFAULT_MODEL", {})
        default_platform = default_config.get("platform")
        default_model = default_config.get("model_name")

        if default_platform and default_model:
            default_pair = (default_platform, default_model)
            if default_pair not in self.available_models:
                self.available_models.append(default_pair)

    def add_model(self, model_instance: 'LLMmodel'):
        """
        添加模型到列表
        :param model_instance:
        :return:
        """
        model_key = self._get_model_key(model_instance.platform, model_instance.model_name)
        self.instantiated_models[model_key] = model_instance

        model_pair = (model_instance.platform, model_instance.model_name)
        if model_pair not in self.available_models:
            self.available_models.append(model_pair)

    def set_current_model(self, model_instance: 'LLMmodel'):
        """
        设置当前模型（由外部创建模型实例后调用）
        :param model_instance:
        """
        self.add_model(model_instance)
        model_key = self._get_model_key(model_instance.platform, model_instance.model_name)
        self.current_model = model_instance
        self.current_model_key = model_key

    def get_current_model(self) -> 'LLMmodel':
        """
        获取当前模型
        :return:
        """
        if self.current_model is None:
            raise ValueError("当前没有设置模型")
        return self.current_model

    def switch_model(self, platform: str, model_name: str) -> bool:
        """
        模型切换
        :param platform:
        :param model_name:
        :return:
        """
        if (platform, model_name) not in self.available_models:
            return False

        model_key = self._get_model_key(platform, model_name)

        if model_key in self.instantiated_models:
            self.current_model = self.instantiated_models[model_key]
            self.current_model_key = model_key
            return True

        try:
            new_model = LLMmodel(platform=platform, model_name=model_name)
            self.add_model(new_model)
            self.current_model = new_model
            self.current_model_key = model_key
            return True
        except Exception:
            return False

    def get_available_models(self) -> List[Tuple[str, str]]:
        return self.available_models.copy()

    def get_instantiated_models(self) -> Dict[str, 'LLMmodel']:
        return self.instantiated_models.copy()


if __name__ == '__main__':
    print("=== 模型管理器测试 ===\n")

    manager = ModelManager()
    print("1. ModelManager实例创建成功")

    try:
        manager.load_config_models()
        available = manager.get_available_models()
        print(f"2. 加载配置文件成功，可用模型数量: {len(available)}")
        print("   可用模型列表:")
        for i, (platform, model_name) in enumerate(available, 1):
            print(f"   {i}. {platform} - {model_name}")
    except Exception as e:
        print(f"2. 加载配置文件失败: {e}")
        exit(1)

    try:
        # 创建默认模型（模拟FastAPI主文件中的初始化）
        default_model = LLMmodel()  # 使用配置文件默认
        manager.set_current_model(default_model)
        print(f"\n3. 默认模型设置成功")
        print(f"   当前模型: {default_model.platform} - {default_model.model_name}")

        current = manager.get_current_model()
        print(f"   获取当前模型验证: {current.platform} - {current.model_name}")
    except Exception as e:
        print(f"3. 默认模型设置失败: {e}")
        exit(1)

    print(f"\n4. 已实例化模型数量: {len(manager.get_instantiated_models())}")

    if len(available) > 1:
        test_platform, test_model = available[1]
        print(f"\n5. 测试切换到第二个模型: {test_platform} - {test_model}")

        if manager.switch_model(test_platform, test_model):
            new_current = manager.get_current_model()
            print(f"   切换成功，当前模型: {new_current.platform} - {new_current.model_name}")
            print(f"   已实例化模型数量: {len(manager.get_instantiated_models())}")
        else:
            print("   切换失败")

    print(f"\n=== 测试完成 ===")
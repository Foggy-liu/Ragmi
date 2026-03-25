# test_simple.py
from model_manager import ModelManager
from utils.models.model_setting import LLMmodel

# 初始化
print("=== 模型管理器测试 ===\n")
manager = ModelManager()
manager.load_config_models()

# 创建并设置默认模型
default_model = LLMmodel()
manager.set_current_model(default_model)
print(f"1. 默认模型: {default_model.platform} - {default_model.model_name}")

# 第一次对话
messages = [{"role": "user", "content": "你是谁？"}]
response1 = manager.get_current_model().invoke(messages)
print(f"2. 第一次对话回答: {response1}")

# 获取可用列表
available = manager.get_available_models()
print(f"\n3. 可用模型列表:")
for i, (p, m) in enumerate(available, 1):
    print(f"   {i}. {p} - {m}")

# 切换到第二个模型
if len(available) > 1:
    platform, model_name = available[2]  # 第二个模型
    print(f"\n4. 切换到第二个模型: {platform} - {model_name}")
    success = manager.switch_model(platform, model_name)
    print(f"   切换结果: {'成功' if success else '失败'}")
    print(f"   当前模型: {manager.current_model.platform} - {manager.current_model.model_name}")

# 第二次对话
response2 = manager.get_current_model().invoke(messages)
print(f"\n5. 第二次对话回答: {response2}")

print(f"\n已实例化模型数量: {len(manager.get_instantiated_models())}")
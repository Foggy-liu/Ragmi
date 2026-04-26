# NEW_FILE_CODE
"""
Agent 使用示例和测试脚本
"""
from utils.models.model_manager import ModelManager
from utils.models.embedding_model import EmbeddingModel
from agent.controller import AgentController


def test_agent():
    """测试 Agent 功能"""
    print("=== Agent 功能测试 ===\n")

    # 1. 初始化模型管理器
    model_manager = ModelManager()
    model_manager.load_config_models()

    # 设置默认模型
    from utils.models.model_setting import LLMmodel
    default_model = LLMmodel()
    model_manager.set_current_model(default_model)

    # 2. 创建 Agent 控制器
    agent = AgentController(model_manager)

    # 3. 测试不同类型的问题
    test_cases = [
        {
            "query": "你好，很高兴认识你",
            "expected": "chat"
        },
        {
            "query": "帮我写一段 Python 代码，实现快速排序",
            "expected": "chat"
        },
        {
            "query": "中华人民共和国刑法是什么时候施行的？",
            "expected": "rag"
        },
        {
            "query": "今天天气不错，推荐一些户外活动吧",
            "expected": "chat"
        },
        {
            "query": "劳动法关于加班工资的规定是什么？",
            "expected": "rag"
        }
    ]

    session_id = None

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*50}")
        print(f"测试{i}: {test_case['query']}")
        print(f"预期工具：{test_case['expected']}")
        print("-" * 50)

        result = agent.decide_and_act(test_case['query'], session_id)

        print(f"实际使用工具：{result['tool_used']}")
        print(f"回答：{result['response'][:200]}...")
        print(f"推理过程：{result['reasoning'][:150]}...")

        session_id = result['session_id']  # 保持会话

    print(f"\n{'='*50}")
    print("测试完成！")


if __name__ == "__main__":
    test_agent()

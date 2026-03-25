from typing import Dict, List, Optional
import uuid
from utils.message.message import MessageManager

# 创建全局的单例 MessageManager
_global_msg_manager = MessageManager()

class ChatModel:
    def __init__(self, model_manager):
        self.model_manager = model_manager
        # self.msg_manager = MessageManager()
        # 使用全局的 MessageManager，而不是每次创建新的
        self.msg_manager = _global_msg_manager

    def chat(self, query: str, session_id: str = None) -> Dict[str, str]:
        """主业务：输入字符串，输出字符串"""
        # 1. 会话管理
        session_id = self.msg_manager.ensure_session(session_id)

        # 2. 构造消息体
        messages = self.msg_manager.build_messages(session_id, query)

        # 3. 调用模型
        model = self.model_manager.get_current_model()
        response = model.invoke(messages)

        # 4. 保存历史
        self.msg_manager.add_to_history(session_id, query, response)

        # 5. 返回字符串
        return {"response": response}

# class ChatModel:
#     def __init__(self, model_manager):
#         """初始化聊天模型"""
#         self.model_manager = model_manager
#         self.session_store = {}  # 临时存储会话历史
#
#     def chat(self, query: str, session_id: str = None) -> Dict:
#         """处理聊天请求"""
#         # 获取当前模型实例
#         current_model = self.model_manager.get_current_model()
#
#         # 处理会话ID
#         if not session_id:
#             session_id = str(uuid.uuid4())
#             self.session_store[session_id] = []
#
#         # 获取历史消息
#         history = self.session_store.get(session_id, [])
#
#         # 添加用户消息
#         history.append({"role": "user", "content": query})
#
#         # 调用模型生成回复
#         response = current_model.invoke(history)
#
#         # 添加助手回复
#         history.append({"role": "assistant", "content": response})
#
#         # 限制历史长度并保存
#         if len(history) > 10:
#             history = history[-10:]
#         self.session_store[session_id] = history
#
#         return {
#             "reply": response,
#             "session_id": session_id
#         }
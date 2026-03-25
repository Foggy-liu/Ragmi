from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from typing import List
import uuid


class MessageManager:
    def __init__(self):
        self.sessions = {}  # session_id -> {"system": str, "history": list}

    def ensure_session(self, session_id: str = None) -> str:
        if not session_id:
            session_id = str(uuid.uuid4())

        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "system": "",
                "history": []
            }

        return session_id

    def build_messages(self, session_id: str, query: str, custom_system: str = None) -> List:
        """构造完整的消息列表"""
        session = self.sessions[session_id]

        # 1. 系统消息（优先使用custom_system，否则用session中的）
        system_content = custom_system if custom_system is not None else session["system"]
        messages = [SystemMessage(content=system_content)]

        # 2. 历史消息
        messages.extend(session["history"])

        # 3. 当前用户消息
        messages.append(HumanMessage(content=query))

        return messages

    def add_to_history(self, session_id: str, query: str, response: str):
        """保存对话到历史"""
        session = self.sessions[session_id]

        # 直接添加HumanMessage和AIMessage对象
        session["history"].append(HumanMessage(content=query))
        session["history"].append(AIMessage(content=response))

        # 限制长度
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]

        # 调试：打印添加后的历史
        print("DEBUG 添加后的历史:")
        for i, msg in enumerate(session["history"]):
            if isinstance(msg, HumanMessage):
                print(f"  [{i}] 用户: {msg.content}")
            else:
                print(f"  [{i}] 助手: {msg.content[:50]}...")

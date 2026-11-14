import os
from pathlib import Path

from sqlalchemy import select
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from dotenv import load_dotenv

from my_ai_project.mt_connect import my_database

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# api_key 走系统环境变量（进程环境变量 ai_key），base_url 来自 .env
model = init_chat_model(
    model="qwen-plus",
    model_provider="openai",
    api_key=os.getenv("ai_key"),
    base_url=os.getenv("BAILIAN_AI_URL"),
)


async def load_history_messages(conn, user_id: str, limit: int = 20):
    """从历史库按时间正序读取最近的对话，转成 LangChain 消息列表。"""
    rows = await conn.scalars(
        select(my_database.Content)
        .where(my_database.Content.user_id == user_id)
        .order_by(my_database.Content.create_time.desc())
        .limit(limit)
    )
    items = list(rows)[::-1]  # 反转为时间正序

    messages = [
        SystemMessage("你是一个简洁、友善的 AI 助手，请结合下方历史对话回答当前问题，回答使用 Markdown 格式。")
    ]
    for row in items:
        if row.role == "user":
            messages.append(HumanMessage(row.message))
        else:
            messages.append(AIMessage(row.message))
    return messages


async def build_agent(user_id: str, conn):
    """构建 agent（当前不携带工具）。历史消息在调用处通过 load_history_messages 传入。"""
    agent = create_agent(
        model=model,
        tools=[],
    )
    return agent

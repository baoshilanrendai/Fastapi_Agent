import os
import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Integer,
    Enum,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

async_engine = create_async_engine(os.getenv("MYSQL_URL"))


class Base(DeclarativeBase):
    pass


# 用户表：账号密码登录
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(32), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)  # 存哈希，不存明文
    create_time = Column(DateTime, default=datetime.now)


# 历史库：一条记录一行，一轮对话占两行（user / assistant），按会话分组
class Content(Base):
    __tablename__ = "content"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(32), index=True, nullable=False)
    conversation_id = Column(String(36), index=True, nullable=False)
    role = Column(Enum("user", "assistant"), nullable=False)
    message = Column(Text, nullable=False)
    create_time = Column(DateTime, default=datetime.now)


# 会话库：一个会话一条记录，标题取首条用户问题
class Conversation(Base):
    __tablename__ = "conversation"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(32), index=True, nullable=False)
    title = Column(String(128), default="新会话")
    create_time = Column(DateTime, default=datetime.now)


# 任务库：只记任务 id、所属会话、所属用户、状态、时间
class TaskChat(Base):
    __tablename__ = "task_chat"

    task_id = Column(String(36), primary_key=True)
    user_id = Column(String(32), index=True, nullable=False)
    conversation_id = Column(String(36), index=True, nullable=False)
    state = Column(
        Enum("失败", "未完成", "进行中", "已完成"),
        default="未完成",
        nullable=False,
    )
    create_time = Column(DateTime, default=datetime.now)


Asyncsession = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def hash_password(raw: str) -> str:
    """简单口令哈希"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_async_session():
    async with Asyncsession() as async_session:
        yield async_session


async def init_db():
    """启动时建表"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

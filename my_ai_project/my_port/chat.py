import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from my_ai_project.mt_connect import my_database
from my_ai_project.mt_connect.auth import get_current_user, login, register

router = APIRouter(prefix="/api", tags=["会话"])


class Auth_Base(BaseModel):
    username: str
    password: str


class Conversation_Base(BaseModel):
    title: str | None = None


@router.post("/register")
async def register_api(body: Auth_Base, conn=Depends(my_database.get_async_session)):
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    return await register(body.username, body.password, conn)


@router.post("/login")
async def login_api(body: Auth_Base, conn=Depends(my_database.get_async_session)):
    return await login(body.username, body.password, conn)


@router.get("/me")
async def me(current=Depends(get_current_user),
             conn=Depends(my_database.get_async_session)):
    """当前登录用户信息 + 主页统计（会话数、消息数）。"""
    conv_count = await conn.scalar(
        select(func.count(my_database.Conversation.id)).where(
            my_database.Conversation.user_id == current["user_id"]
        )
    )
    msg_count = await conn.scalar(
        select(func.count(my_database.Content.id)).where(
            my_database.Content.user_id == current["user_id"]
        )
    )
    return {
        "user_id": current["user_id"],
        "username": current["username"],
        "conversation_count": conv_count or 0,
        "message_count": msg_count or 0,
    }


@router.get("/conversations")
async def list_conversations(
    current=Depends(get_current_user),
    conn=Depends(my_database.get_async_session),
):
    """当前用户的会话列表，按最近活跃倒序。"""
    rows = await conn.scalars(
        select(my_database.Conversation)
        .where(my_database.Conversation.user_id == current["user_id"])
        .order_by(my_database.Conversation.create_time.desc())
    )
    conversations = [
        {"conversation_id": row.id, "title": row.title, "create_time": row.create_time}
        for row in rows
    ]
    return {"conversations": conversations}


@router.post("/conversations")
async def create_conversation(
    body: Conversation_Base,
    current=Depends(get_current_user),
    conn=Depends(my_database.get_async_session),
):
    """新建一个空会话，返回 conversation_id。"""
    conv_id = str(uuid.uuid4())
    conv = my_database.Conversation(
        id=conv_id,
        user_id=current["user_id"],
        title=(body.title or "新会话").strip()[:128] or "新会话",
    )
    conn.add(conv)
    await conn.commit()
    return {"conversation_id": conv_id, "title": conv.title}


@router.get("/history")
async def history(
    conversation_id: str,
    current=Depends(get_current_user),
    conn=Depends(my_database.get_async_session),
):
    """拉取指定会话的历史消息（时间正序）。"""
    conv = await conn.scalar(
        select(my_database.Conversation).where(
            my_database.Conversation.id == conversation_id,
            my_database.Conversation.user_id == current["user_id"],
        )
    )
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    rows = await conn.scalars(
        select(my_database.Content)
        .where(
            my_database.Content.user_id == current["user_id"],
            my_database.Content.conversation_id == conversation_id,
        )
        .order_by(my_database.Content.create_time.asc())
    )
    messages = [{"role": row.role, "content": row.message} for row in rows]
    return {"messages": messages}

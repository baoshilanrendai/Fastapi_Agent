import uuid
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Header
from sqlalchemy import select

from my_ai_project.mt_connect import my_database

# 内存 token 表：token -> (user_id, expire_at)
# 重启后失效；生产环境建议改存 Redis，设过期时间
_TOKEN_TTL = timedelta(days=7)
_token_store: dict[str, tuple[str, datetime]] = {}


def _issue_token(user_id: str) -> str:
    token = uuid.uuid4().hex
    _token_store[token] = (user_id, datetime.now() + _TOKEN_TTL)
    return token


def _resolve_token(token: str) -> str:
    record = _token_store.get(token)
    if not record:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    user_id, expire_at = record
    if expire_at < datetime.now():
        _token_store.pop(token, None)
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user_id


async def register(username: str, password: str, conn):
    exists = await conn.scalar(
        select(my_database.User).where(my_database.User.username == username)
    )
    if exists:
        raise HTTPException(status_code=400, detail="用户名已被注册")
    user = my_database.User(
        username=username,
        password_hash=my_database.hash_password(password),
    )
    conn.add(user)
    await conn.commit()
    await conn.refresh(user)
    token = _issue_token(str(user.id))
    return {"token": token, "username": username, "user_id": str(user.id)}


async def login(username: str, password: str, conn):
    user = await conn.scalar(
        select(my_database.User).where(my_database.User.username == username)
    )
    if not user or user.password_hash != my_database.hash_password(password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = _issue_token(str(user.id))
    return {"token": token, "username": user.username, "user_id": str(user.id)}


async def get_current_user(
    authorization: str = Header(default=""),
    conn=Depends(my_database.get_async_session),
) -> dict:
    """依赖：从 Authorization: Bearer <token> 解析当前登录用户。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少登录凭证")
    token = authorization.split(" ", 1)[1].strip()
    user_id = _resolve_token(token)
    user = await conn.get(my_database.User, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return {"user_id": str(user.id), "username": user.username}

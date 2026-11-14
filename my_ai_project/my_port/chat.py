from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from my_ai_project.mt_connect import my_database, my_auth

router = APIRouter(prefix="/api", tags=["会话"])


class Auth_Base(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(body: Auth_Base, conn=Depends(my_database.get_async_session)):
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    return await my_auth.register(body.username, body.password, conn)


@router.post("/login")
async def login(body: Auth_Base, conn=Depends(my_database.get_async_session)):
    return await my_auth.login(body.username, body.password, conn)


@router.get("/history")
async def history(current=Depends(my_auth.get_current_user),
                  conn=Depends(my_database.get_async_session)):
    rows = await conn.scalars(
        select(my_database.Content)
        .where(my_database.Content.user_id == current["user_id"])
        .order_by(my_database.Content.create_time.asc())
    )
    messages = [{"role": row.role, "content": row.message} for row in rows]
    return {"messages": messages}

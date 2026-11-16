import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from my_ai_project.mt_connect import my_database, my_redis
from my_ai_project.mt_connect.auth import get_current_user

router = APIRouter(prefix="/ai_chat", tags=["ai会话"])


class Chat_Base(BaseModel):
    question: str
    conversation_id: str


@router.post("/input_chat")
async def chat(
    params: Chat_Base,
    current=Depends(get_current_user),
    conn=Depends(my_database.get_async_session),
):
    task_id = str(uuid.uuid4())
    user_id = current["user_id"]
    conversation_id = params.conversation_id

    # 校验会话归属，避免跨用户写入
    conv = await conn.scalar(
        select(my_database.Conversation).where(
            my_database.Conversation.id == conversation_id,
            my_database.Conversation.user_id == user_id,
        )
    )
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 首条问题作为会话标题（空会话标题仍是“新会话”时更新）
    if conv.title in (None, "", "新会话"):
        conv.title = params.question.strip()[:128] or "新会话"

    # 任务库只记 task_id、user_id、conversation_id、状态，不记消息正文
    conn.add(
        my_database.TaskChat(
            task_id=task_id,
            user_id=user_id,
            conversation_id=conversation_id,
            state="未完成",
        )
    )
    await conn.commit()

    # 消息正文（问题、user_id、会话ID）放进 Redis 队列，等待 worker 抢任务消费
    msg = json.dumps(
        {
            "task_id": task_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "question": params.question.strip(),
        },
        ensure_ascii=False,
    )
    await my_redis.redis_client.lpush(my_redis.QUEUE_KEY, msg)
    return {"task_id": task_id, "msg": "提交成功"}


@router.get("/task")
async def get_task(
    task_id: str,
    current=Depends(get_current_user),
    conn=Depends(my_database.get_async_session),
):
    res = await conn.scalar(
        select(my_database.TaskChat).where(my_database.TaskChat.task_id == task_id)
    )
    if not res:
        return {"code": 404, "msg": "不存在"}
    return {"task_id": task_id, "state": res.state}


@router.get("/stream/{task_id}")
async def stream_result(
    task_id: str,
    current=Depends(get_current_user),
):
    """前端订阅某任务的流式结果：从 Redis 结果通道逐条读取 worker 写入的分片，SSE 推给浏览器。"""
    key = my_redis.result_key(task_id)

    async def event_generator():
        last_index = 0
        idle_rounds = 0
        MAX_IDLE = 60  # 最多空闲等待约 60 秒（每次 blpop 阻塞 1s）

        while True:
            # 先取通道里已堆积的历史分片（含订阅前 worker 已写入的部分）
            events = await my_redis.redis_client.lrange(key, last_index, -1)
            for evt in events:
                last_index += 1
                try:
                    data = json.loads(evt)
                except Exception:
                    continue
                yield _sse(data["event"], data["data"])
                if data["event"] in ("done", "error"):
                    return

            # 没有新分片则阻塞等 1 秒，避免空转
            popped = await my_redis.redis_client.blpop(key, timeout=1)
            if popped:
                idle_rounds = 0
                _, evt = popped
                last_index += 1
                try:
                    data = json.loads(evt)
                except Exception:
                    continue
                yield _sse(data["event"], data["data"])
                if data["event"] in ("done", "error"):
                    return
            else:
                idle_rounds += 1
                if idle_rounds >= MAX_IDLE:
                    yield _sse("error", {"detail": "等待任务结果超时"})
                    return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

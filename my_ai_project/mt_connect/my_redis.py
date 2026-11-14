import os
import json
from pathlib import Path

import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

QUEUE_KEY = "agent_task_queue"
RESULT_TTL = 600  # 结果通道保留时长（秒），过期自动清理


def result_key(task_id: str) -> str:
    """worker 流式输出按 task_id 写入的结果列表 key。"""
    return f"agent_result:{task_id}"


redis_client = redis.from_url(
    os.getenv("REDIS_URL"),
    decode_responses=True,  # 队列/结果消息是 JSON 字符串，直接解出 str
    protocol=2,  # Redis 5.x 不支持 RESP3，固定 RESP2 协议
)


async def push_event(task_id: str, event: str, data: dict):
    """worker 向某任务的结果通道写入一条 SSE 事件，并设置过期时间。"""
    key = result_key(task_id)
    await redis_client.rpush(key, json.dumps({"event": event, "data": data}, ensure_ascii=False))
    await redis_client.expire(key, RESULT_TTL)

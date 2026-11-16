import asyncio
import json

from sqlalchemy import select
from langchain_core.messages import HumanMessage

from my_ai_project.common import get_logger
from my_ai_project.mt_connect import my_redis, my_agent, my_database

logger = get_logger(__name__)

MAX_RETRY = 3  # 同一任务最多重试次数


async def _mark_state(task_id: str, state: str):
    async with my_database.Asyncsession() as conn:
        task = await conn.scalar(
            select(my_database.TaskChat).where(my_database.TaskChat.task_id == task_id)
        )
        if task:
            task.state = state
            await conn.commit()


async def worker_loop():
    while True:
        # blpop 返回 (key, value) 二元组；Redis 连接异常时退避后重连，避免进程退出
        try:
            popped = await my_redis.redis_client.blpop(my_redis.QUEUE_KEY, timeout=1)
        except Exception as e:
            logger.warning("Redis 连接异常，3 秒后重连：%s", e)
            await asyncio.sleep(3)
            continue
        if not popped:
            continue

        _, raw = popped
        try:
            task = json.loads(raw)
            task_id = task["task_id"]
            user_id = task["user_id"]
            conversation_id = task["conversation_id"]
            question = task["question"]
            retry = int(task.get("retry", 0))
        except Exception as e:
            logger.error("消息解析失败，丢弃：%s | %s", raw, e)
            continue

        logger.info("抢到任务：%s（会话 %s）", task_id, conversation_id)

        try:
            async with my_database.Asyncsession() as conn:
                # 1. 读取本会话历史、构建 agent
                messages = await my_agent.load_history_messages(
                    conn, user_id, conversation_id
                )
                messages.append(HumanMessage(question))

                agent = await my_agent.build_agent(user_id, conn)

                # 2. 任务状态置为进行中
                task_row = await conn.scalar(
                    select(my_database.TaskChat).where(
                        my_database.TaskChat.task_id == task_id
                    )
                )
                if task_row:
                    task_row.state = "进行中"
                    await conn.commit()

                # 3. 流式调用大模型，逐 token 写入 Redis 结果通道
                answer_parts = []
                async for message_chunk in agent.astream(
                    {"messages": messages}, stream_mode="messages"
                ):
                    msg = message_chunk[0] if isinstance(message_chunk, tuple) else message_chunk
                    if hasattr(msg, "content") and msg.content:
                        answer_parts.append(msg.content)
                        await my_redis.push_event(task_id, "delta", {"content": msg.content})

                answer = "".join(answer_parts).strip() or "（模型未返回内容）"

                # 4. 历史库按一轮两行落库（user 问题 + assistant 回答），归属本会话
                conn.add(my_database.Content(
                    user_id=user_id, conversation_id=conversation_id,
                    role="user", message=question,
                ))
                conn.add(my_database.Content(
                    user_id=user_id, conversation_id=conversation_id,
                    role="assistant", message=answer,
                ))

                # 5. 任务状态置为已完成，推送完成事件
                if task_row:
                    task_row.state = "已完成"
                await conn.commit()

                await my_redis.push_event(task_id, "done", {"content": answer})

        except Exception as e:
            logger.exception("任务执行出现异常：%s", task_id)
            try:
                await _mark_state(task_id, "失败")
            except Exception as mark_err:
                logger.error("状态回写失败：%s", mark_err)

            await my_redis.push_event(task_id, "error", {"detail": str(e)})

            # 未超上限才回队重试；超过则丢弃，避免死循环
            if retry < MAX_RETRY:
                task["retry"] = retry + 1
                await my_redis.redis_client.lpush(
                    my_redis.QUEUE_KEY, json.dumps(task, ensure_ascii=False)
                )
            else:
                logger.warning("任务 %s 超过最大重试次数，不再入队", task_id)
            continue


if __name__ == "__main__":
    asyncio.run(worker_loop())

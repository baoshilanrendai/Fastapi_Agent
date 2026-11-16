"""统一日志模块。

- 按模块名取 logger，避免各处重复配置；
- 控制台 + 文件双输出，文件按天滚动、保留 7 天，目录在项目根的 logs/ 下；
- 日志级别可通过环境变量 LOG_LEVEL 覆盖（DEBUG / INFO / WARNING / ERROR）。

用法：

    from my_ai_project.common import get_logger

    logger = get_logger(__name__)
    logger.info("抢到任务：%s", task_id)
"""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 项目根目录（my_ai_project 的上一级），日志统一落到 <根>/logs/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"

# 同一进程内只初始化一次根 handler，避免重复挂 handler 导致日志重复打印
_initialized = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, level_name, logging.INFO)


def _setup_root_handlers() -> None:
    """首次调用时给根 logger 挂控制台 + 文件 handler。"""
    global _initialized
    if _initialized:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = _resolve_level()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清掉默认 handler，防止 uvicorn 等框架残留配置干扰
    root_logger.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件输出：按天滚动，保留最近 7 天
    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = TimedRotatingFileHandler(
        _LOG_DIR / f"app-{today}.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """按模块名返回 logger；首次调用完成全局 handler 初始化。"""
    _setup_root_handlers()
    return logging.getLogger(name)

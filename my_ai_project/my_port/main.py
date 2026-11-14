from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from my_ai_project.my_port import ai, chat
from my_ai_project.mt_connect import my_database

app = FastAPI(title="agent 项目")

# 允许本地跨域调试（前端独立端口时使用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent / "static"


@app.on_event("startup")
async def on_startup():
    await my_database.init_db()


app.include_router(ai.router)
app.include_router(chat.router)

# 前端静态页面
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


@app.post("/root")
async def root():
    return "欢迎"

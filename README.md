# 基于 FastAPI + Redis 队列的 AI 对话助手（LangChain 接入大模型）

一个异步架构的 Web AI 对话项目：前端提交问题后进入 Redis 任务队列，后台 Worker 消费任务并流式调用大模型，结果经 Redis 结果通道以 SSE 推回浏览器，支持 Markdown 渲染、代码高亮、多轮历史记忆与账号登录。

---

## 一、项目简介

本项目是一个前后端分离（后端同时托管静态页面）的 AI 对话应用，核心特点：

- **异步任务队列架构**：请求不直接阻塞等待模型生成，而是写入 Redis 队列，由独立 Worker 进程消费，便于后续扩展并发与长任务。
- **流式输出（SSE）**：Worker 逐 token 调用大模型，分片写入 Redis 结果通道，前端通过 SSE 订阅任务结果，实现回答逐字上屏。
- **多轮对话记忆**：历史对话按「一轮两行（user / assistant）」落库，每次请求加载历史上下文拼入消息列表。
- **账号体系**：注册 / 登录，密码哈希存储，Bearer Token 鉴权。
- **Markdown 渲染**：前端 marked 解析 + DOMPurify 消毒 + highlight.js 代码高亮。

## 二、技术栈

| 层级 | 技术 |
| --- | --- |
| 后端框架 | FastAPI（异步 ASGI）、Uvicorn |
| 大模型接入 | LangChain 1.5、langchain-openai（OpenAI 兼容协议接入通义千问 qwen-plus） |
| 任务队列 / 缓存 | Redis（redis-py 异步客户端，RESP2） |
| 数据库 | MySQL 8.0、SQLAlchemy 2.0 异步 ORM、aiomysql |
| 鉴权 | 自研 Bearer Token（内存存储，可扩展至 Redis / JWT） |
| 前端 | 原生 HTML / CSS / JavaScript，marked、DOMPurify、highlight.js（CDN） |
| 环境管理 | Python 3.13、uv 依赖管理、python-dotenv |

## 三、系统架构

```
浏览器 (index.html)
   │  ① POST /ai_chat/input_chat  提交问题 → 写任务库 + 问题入 Redis 队列
   │  ② GET  /ai_chat/stream/{task_id}  SSE 订阅该任务的流式结果
   ▼
FastAPI 后端 (my_port)
   │  ③ LPUSH 任务到 Redis 队列 agent_task_queue
   ▼
Redis
   ├── 任务队列 agent_task_queue（LPUSH / BLPOP）
   └── 结果通道 agent_result:{task_id}（按任务存流式分片，TTL 600s）
   ▲
   │  ④ BLPOP 抢任务 → 读历史 → astream 逐 token → 分片写结果通道 → 落历史库
后台 Worker 进程 (my_workers)
   ▼
MySQL：users（账号）、content（历史对话）、task_chat（任务状态）
```

### 数据流说明

1. 用户在前端提交问题，后端生成 `task_id`，在任务库写入一条「未完成」记录，并把 `{task_id, user_id, question}` 推入 Redis 队列。
2. Worker 阻塞 `BLPOP` 抢到任务，从历史库加载该用户的近期对话作为上下文，调用 LangChain Agent 流式生成。
3. 模型每产出一段增量，Worker 就把 `delta` 事件写入该任务的 Redis 结果通道；生成结束后写入 `done` 事件并落库本轮问答。
4. 前端凭 `task_id` 订阅结果通道，逐条读取 SSE 事件，逐字渲染 Markdown；任务异常时推送 `error` 事件并按次数回队重试（上限 3 次）。

## 四、目录结构

```
p1/
├── pyproject.toml                  # 依赖与项目元数据（uv 管理）
├── start.ps1                       # 一键启动 Redis + 后端 + Worker
├── stop.ps1                        # 一键停止全部服务
├── .env.example                    # 环境变量模板（实际 .env 不入库）
└── my_ai_project/
    ├── .env                        # 本地环境变量（数据库 / Redis / 模型地址 / MCP）
    ├── common/                     # 跨层公共工具
    │   └── logger.py               # 统一日志：控制台 + 按天滚动文件
    ├── mt_connect/                 # 基础设施连接层
    │   ├── my_database.py          # SQLAlchemy 引擎、ORM 模型、会话工厂、建表
    │   ├── my_redis.py             # Redis 客户端、结果通道写入封装
    │   ├── my_agent.py             # 模型初始化、历史消息加载、Agent 构建（挂载 MCP 工具）
    │   ├── auth/                   # 认证鉴权子包
    │   │   └── my_auth.py          # 注册 / 登录 / Token 校验依赖
    │   └── mcp/                    # MCP 客户端子包
    │       ├── client.py           # 传输层：连接 / 握手 / 列工具 / 原始调用
    │       └── tools.py            # 适配层：转 LangChain Tool、结果归一化、调用入口
    ├── my_port/                    # FastAPI 接口层
    │   ├── main.py                 # 应用入口、CORS、静态托管、路由挂载
    │   ├── chat.py                 # 注册 / 登录 / 历史记录接口
    │   ├── ai.py                   # 任务提交、任务状态、SSE 流式订阅接口
    │   └── static/index.html       # 前端单页（登录 + 流式对话界面）
    └── my_workers/                 # 后台异步消费进程
        └── main.py                 # 队列消费循环：抢任务 → 流式调用 → 写结果通道 → 落库
```

## 五、数据库表设计

### `users`（用户表）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int, 主键, 自增 | 用户 ID |
| username | varchar(32), 唯一索引 | 用户名 |
| password_hash | varchar(128) | 口令 SHA-256 哈希（不存明文） |
| create_time | datetime | 注册时间 |

### `conversation`（会话表，一个会话一条记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | varchar(36), 主键 | 会话 ID（UUID） |
| user_id | varchar(32), 索引 | 所属用户 ID |
| title | varchar(128) | 会话标题，取首条用户问题 |
| create_time | datetime | 创建时间 |

### `content`（对话历史表，一条记录一行，按会话分组）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int, 主键, 自增 | 记录 ID |
| user_id | varchar(32), 索引 | 所属用户 ID |
| conversation_id | varchar(36), 索引 | 所属会话 ID |
| role | enum(user, assistant) | 消息角色 |
| message | text | 消息内容（Markdown） |
| create_time | datetime | 发言时间 |

### `task_chat`（任务状态表）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| task_id | varchar(36), 主键 | 任务编号（UUID） |
| user_id | varchar(32), 索引 | 所属用户 ID |
| state | enum | 未完成 / 进行中 / 已完成 / 失败 |
| create_time | datetime | 创建时间 |

## 六、接口一览

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/register` | 否 | 注册账号，返回 token |
| POST | `/api/login` | 否 | 登录，返回 token |
| GET | `/api/me` | 是 | 当前用户信息与会话/消息统计 |
| GET | `/api/conversations` | 是 | 会话列表（按最近活跃倒序） |
| POST | `/api/conversations` | 是 | 新建会话，返回 conversation_id |
| GET | `/api/history?conversation_id=` | 是 | 拉取指定会话的历史消息 |
| POST | `/ai_chat/input_chat` | 是 | 提交问题（带 conversation_id），生成任务入队 |
| GET | `/ai_chat/stream/{task_id}` | 是 | SSE 订阅任务流式结果 |
| GET | `/ai_chat/task` | 是 | 查询任务状态 |

SSE 事件格式：

```
event: delta
data: {"content": "逐段增量文本"}

event: done
data: {"content": "完整回答"}

event: error
data: {"detail": "错误信息"}
```

## 七、本地运行

### 1. 环境准备

- Python 3.13，已安装 [uv](https://docs.astral.sh/uv/)
- 本地 MySQL 8.0（库名 `ai`）、Redis 5.x+

### 2. 安装依赖

```powershell
uv sync
```

### 3. 配置环境变量

复制 `my_ai_project/.env.example` 为 `my_ai_project/.env`，填写：

```ini
# 大模型 OpenAI 兼容接口地址
BAILIAN_AI_URL='https://your-model-endpoint/v1'
# 数据库连接
MYSQL_URL='mysql+aiomysql://root:密码@127.0.0.1:3306/ai'
# Redis 连接
REDIS_URL='redis://127.0.0.1:6379/0'
```

> 大模型 API Key 从系统环境变量 `ai_key` 读取，不写入 `.env`。

MCP 客户端可接入外部 MCP server，工具会自动挂载到 Agent：

```ini
MCP_TRANSPORT='stdio'                 # stdio（本地子进程）或 http（远程端点）
MCP_COMMAND='python'                  # stdio：启动命令
MCP_ARGS='-m,your_mcp_server_module'  # stdio：参数，逗号分隔
MCP_URL='http://127.0.0.1:8000/mcp'   # http：端点地址
```

> MCP 连接失败时自动降级为纯模型对话，不阻断主流程；日志写入 `logs/` 目录。

### 4. 启动服务

在项目根目录执行一键脚本（Windows PowerShell）：

```powershell
.\start.ps1
```

脚本会依次启动 Redis、FastAPI 后端、Worker；停止执行：

```powershell
.\stop.ps1
```

手动分步启动（等价方式）：

```powershell
# Redis
.\my_ai_project\Redis-x64-5.0.14.1\redis-server.exe .\my_ai_project\Redis-x64-5.0.14.1\redis.windows.conf

# 后端（默认 8001 端口）
.\.venv\Scripts\python.exe -m uvicorn my_ai_project.my_port.main:app --host 127.0.0.1 --port 8001

# Worker（必须启动，否则任务入队后无人消费）
.\.venv\Scripts\python.exe -m my_ai_project.my_workers.main
```

浏览器访问 `http://127.0.0.1:8001`，先注册账号再对话；接口文档见 `/docs`。

## 八、关键实现点

- **异步 ORM**：SQLAlchemy 2.0 `async_sessionmaker` + aiomysql，FastAPI 依赖注入获取会话。
- **流式调用**：`agent.astream(..., stream_mode="messages")` 逐 token 消费，避免一次性等待完整回答。
- **结果回传**：任务队列与结果通道分离——队列只负责派发任务，结果按 `task_id` 独立存储，前端按任务订阅，解耦生产与消费。
- **历史上下文**：按时间正序取最近 20 轮，转成 `HumanMessage / AIMessage` 拼入消息列表。
- **失败重试**：Worker 捕获异常后将任务状态置为「失败」，未超过重试上限则回队重试，防止代码类故障无限循环。
- **前端安全**：Markdown 经 DOMPurify 消毒后再渲染，避免 XSS。

## 九、已知限制与可改进方向

- Token 目前存后端内存，服务重启后需重新登录；可改为 Redis 存储或签发 JWT。
- 口令哈希使用 SHA-256，生产环境建议替换为 bcrypt / passlib。
- 历史仅保留最近 20 轮，长对话可增加摘要压缩或向量检索（RAG）。
- 单 Worker 消费，可按队列分组扩展多 Worker 并发；任务状态可接入延迟重试与死信队列。
- CORS 当前放开 `*`，上线前应按域名收敛。

## 十、简历可写要点（参考）

> 基于 FastAPI + Redis 队列的异步 AI 对话助手，接入 LangChain 调用通义千问大模型；设计「请求入队 → Worker 消费 → 流式结果回传」的异步架构，通过 SSE 实现回答逐字输出；实现账号注册登录（哈希口令 + Bearer Token）、多轮对话历史记忆、Markdown 渲染与代码高亮；使用 SQLAlchemy 异步 ORM 操作 MySQL，Redis 承担任务队列与按任务隔离的结果通道。

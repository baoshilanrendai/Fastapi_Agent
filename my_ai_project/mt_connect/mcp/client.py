"""MCP 客户端传输层。

职责（只负责「怎么连、怎么收发」，不含业务语义）：
- 从环境变量读取 server 配置，支持 stdio（本地子进程）与 streamable-http（远程）两种传输；
- 建立连接并完成 initialize 握手；
- 列出 server 暴露的工具清单；
- 对指定工具发起原始 call_tool 调用；
- 提供上下文管理，退出时自动断开连接、清理子进程 / HTTP 会话。

配置项（写在 ``my_ai_project/.env``）：

    # 传输方式：stdio 或 http
    MCP_TRANSPORT='stdio'

    # --- stdio 方式：拉起本地子进程 ---
    MCP_COMMAND='python'
    MCP_ARGS='-m,your_mcp_server_module'   # 逗号分隔的参数列表

    # --- http 方式：连接远程 MCP 端点 ---
    MCP_URL='http://127.0.0.1:8000/mcp'

用法（长连接复用，推荐）：

    async with McpClient() as client:
        tools = await client.list_tools()
        result = await client.call_tool("search", {"keyword": "langchain"})
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from my_ai_project.common import get_logger

logger = get_logger(__name__)

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


@dataclass
class McpServerConfig:
    """从环境变量解析出的 MCP server 连接配置。"""

    transport: str = "stdio"  # stdio | http
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None

    @classmethod
    def from_env(cls) -> "McpServerConfig":
        transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
        if transport not in ("stdio", "http"):
            raise ValueError(f"未知的 MCP_TRANSPORT：{transport}（仅支持 stdio / http）")

        raw_args = os.getenv("MCP_ARGS", "").strip()
        args = [a.strip() for a in raw_args.split(",") if a.strip()] if raw_args else []

        return cls(
            transport=transport,
            command=os.getenv("MCP_COMMAND") or None,
            args=args,
            url=os.getenv("MCP_URL") or None,
        )


class McpClient:
    """单个 MCP server 的异步客户端，支持 ``async with`` 生命周期管理。

    同一 client 实例内复用一条会话；worker / 接口层需要时再各自建实例。
    """

    def __init__(self, config: McpServerConfig | None = None) -> None:
        self.config = config or McpServerConfig.from_env()
        self._session: ClientSession | None = None
        self._transport_cm: Any = None  # 传输层异步上下文管理器
        self._streams: Any = None

    # ---------------- 生命周期 ----------------

    async def connect(self) -> ClientSession:
        """建立传输连接并完成 MCP 握手，返回会话。重复调用不会重复建连。"""
        if self._session is not None:
            return self._session

        if self.config.transport == "stdio":
            if not self.config.command:
                raise ValueError("stdio 传输需要配置 MCP_COMMAND")
            params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
            )
            self._transport_cm = stdio_client(params)
        else:
            if not self.config.url:
                raise ValueError("http 传输需要配置 MCP_URL")
            self._transport_cm = streamable_http_client(self.config.url)

        self._streams = await self._transport_cm.__aenter__()
        read_stream, write_stream = self._streams
        self._session = ClientSession(read_stream, write_stream)
        await self._session.initialize()
        logger.info("MCP 客户端已连接（%s）", self.config.transport)
        return self._session

    async def close(self) -> None:
        """断开连接并清理传输资源，可重复调用。"""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception as e:
                logger.warning("关闭 MCP 会话时异常：%s", e)
            self._session = None

        if self._transport_cm is not None:
            try:
                await self._transport_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("关闭 MCP 传输层时异常：%s", e)
            self._transport_cm = None
            self._streams = None
        logger.info("MCP 客户端已断开")

    async def __aenter__(self) -> "McpClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---------------- 协议调用（原始结果） ----------------

    async def list_tools(self) -> list[Any]:
        """返回 server 暴露的工具定义列表（mcp Tool 对象）。"""
        session = await self.connect()
        result = await session.list_tools()
        logger.info("MCP 工具清单加载完成，共 %d 个", len(result.tools))
        return result.tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """发起一次 tools/call，返回原始 CallToolResult。"""
        session = await self.connect()
        logger.debug("调用 MCP 工具：%s | 参数=%s", name, arguments)
        return await session.call_tool(name, arguments or {})

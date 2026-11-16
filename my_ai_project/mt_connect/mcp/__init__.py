"""MCP 客户端子包。

分层：
- ``client.py``：传输层，只管连 MCP server、握手、列工具、发起原始调用；
- ``tools.py``：适配层，把 MCP 工具转成 LangChain 可绑定的 Tool，并提供业务调用入口。

对外常用导出：

    from my_ai_project.mt_connect.mcp import McpClient, get_langchain_tools
"""

from my_ai_project.mt_connect.mcp.client import McpClient
from my_ai_project.mt_connect.mcp.tools import get_langchain_tools

__all__ = ["McpClient", "get_langchain_tools"]

"""MCP 工具适配层（业务语义在这里，传输层不碰）。

职责：
- 把 MCP server 暴露的工具转换成 LangChain ``StructuredTool``，可直接喂给 ``build_agent(tools=...)``；
- 统一处理调用结果：抽取文本 / 结构化内容，识别 ``is_error`` 并抛工具异常；
- 提供不经过 LangChain 时的直接调用入口 ``call_mcp_tool``。

说明：本项目未装 ``langchain-mcp-adapters``，这里用原生 MCP SDK + LangChain 工具类手写适配，避免新增依赖。
"""

from typing import Any

from pydantic import BaseModel, create_model
from langchain_core.tools import StructuredTool, ToolException

from my_ai_project.common import get_logger
from my_ai_project.mt_connect.mcp.client import McpClient

logger = get_logger(__name__)


# ---------------- 结果归一化 ----------------

def _extract_text(result: Any) -> str:
    """从 CallToolResult 的 content 列表里拼接纯文本。

    优先返回 structured_content（若为 JSON 可序列化对象则转成文本），
    否则把各 content block 的文本部分拼起来；都没有时返回空串。
    """
    # 结构化内容优先：方便模型直接拿到结构化结果
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return _stringify(structured)

    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        # TextContent 有 .text；图片等其它类型跳过文本抽取
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts).strip()


def _stringify(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _check_result_error(result: Any) -> None:
    """MCP 侧工具报错（is_error=True）时转成 ToolException，便于 LangChain 捕获自纠正。"""
    if getattr(result, "is_error", False):
        detail = _extract_text(result) or "MCP 工具执行返回错误"
        raise ToolException(detail)


# ---------------- Schema 转换 ----------------

def _build_args_schema(tool_name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    """把 MCP 工具的 JSON Schema 转成 Pydantic 模型，供 LangChain 做参数校验。

    仅处理常见的 properties / required；复杂关键字（anyOf、嵌套 $ref 等）回退为宽松 any。
    """
    properties = (input_schema or {}).get("properties", {}) or {}
    required = set((input_schema or {}).get("required", []) or [])

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        py_type = _json_schema_to_python_type(prop_schema)
        default = ... if prop_name in required else None
        fields[prop_name] = (py_type, default)

    if not fields:
        # 工具无入参：给一个空模型，避免 LangChain 推断失败
        fields = {"_": (str | None, None)}

    return create_model(f"McpTool_{tool_name}", **fields)


def _json_schema_to_python_type(prop_schema: dict[str, Any]) -> Any:
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    schema_type = prop_schema.get("type")
    if isinstance(schema_type, list):
        # 形如 ["string", "null"]：取第一个非 null 类型
        schema_type = next((t for t in schema_type if t != "null"), schema_type[0])
    return type_map.get(schema_type, Any)


# ---------------- 对外入口 ----------------

async def call_mcp_tool(
    client: McpClient,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> str:
    """直接调用某个 MCP 工具并归一化为文本结果（不经过 LangChain）。"""
    result = await client.call_tool(name, arguments)
    _check_result_error(result)
    return _extract_text(result)


async def get_langchain_tools(client: McpClient) -> list[StructuredTool]:
    """把连接上的 MCP 工具清单转成 LangChain StructuredTool 列表。

    每个工具闭包持有同一个 client 实例；工具被 Agent 调用时内部走 ``call_mcp_tool``。
    """
    tools: list[StructuredTool] = []
    mcp_tools = await client.list_tools()

    for mcp_tool in mcp_tools:
        tool_name = mcp_tool.name
        description = mcp_tool.description or f"MCP 工具：{tool_name}"
        args_schema = _build_args_schema(tool_name, mcp_tool.input_schema)

        async def _acall(**kwargs: Any) -> str:
            return await call_mcp_tool(client, tool_name, kwargs)

        tools.append(
            StructuredTool.from_function(
                func=None,
                coroutine=_acall,
                name=tool_name,
                description=description,
                args_schema=args_schema,
            )
        )

    logger.info("已适配 %d 个 MCP 工具为 LangChain Tool", len(tools))
    return tools

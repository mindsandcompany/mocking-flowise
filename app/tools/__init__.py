from .web_search import web_search, VisibleWebSearchModel, WEB_SEARCH
from app.mcp import MCP_TOOLS, get_mcp_tool_map
from app.mcp.mcp_tools import initialize_mcp_tools


async def get_tool_map():
    mcp_map = await get_mcp_tool_map()
    return {
        "web_search": web_search,
        **mcp_map,
    }


async def get_visible_tool_map():
    return {
        "web_search": VisibleWebSearchModel,
    }


async def get_tools_for_llm():
    await initialize_mcp_tools()
    return [
        WEB_SEARCH,
        *MCP_TOOLS
    ]

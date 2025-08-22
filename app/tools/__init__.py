from .web_search import web_search, WEB_SEARCH
from .open_url import open, OPEN_URL
from app.mcp import MCP_TOOLS, get_mcp_tool_map


async def get_tool_map():
    mcp_map = await get_mcp_tool_map()
    return {
        "search": web_search,
        "open": open,
        **mcp_map,
    }


async def get_tools_for_llm():
    return [
        WEB_SEARCH,
        OPEN_URL,
        *MCP_TOOLS
    ]

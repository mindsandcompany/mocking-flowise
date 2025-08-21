from .web_search import web_search, WEB_SEARCH
from app.mcp import get_mcp_tool_map
from app.mcp.mcp_tools import MCP_TOOLS


async def get_tool_map():
    mcp_map = await get_mcp_tool_map()
    return {
        "web_search": web_search,
        **mcp_map,
    }


async def get_tools_for_llm():
    print(MCP_TOOLS)
    return [
        WEB_SEARCH,
        *MCP_TOOLS
    ]

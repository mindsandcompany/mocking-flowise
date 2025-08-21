from .mcp_tools import MCP_TOOLS, get_mcp_tool


async def get_mcp_tool_map():
    return {
        tool['function']['name']: get_mcp_tool(tool['function']['name'])
        for tool in MCP_TOOLS
    }

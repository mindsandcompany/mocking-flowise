from .mcp_tools import MCP_TOOLS, get_mcp_tool, initialize_mcp_tools


async def get_mcp_tool_map():
    await initialize_mcp_tools()
    return {
        tool['name']: get_mcp_tool(tool['name'])
        for tool in MCP_TOOLS
    }

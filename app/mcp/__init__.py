from .mcp_tools import MCP_TOOLS, get_mcp_tool


MCP_TOOL_MAP = {
    tool['name']: get_mcp_tool(tool['name'])
    for tool in MCP_TOOLS
}

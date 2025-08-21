from .web_search import web_search, VisibleWebSearchModel, WEB_SEARCH
from app.mcp import MCP_TOOLS, MCP_TOOL_MAP


TOOL_MAP = {
    "web_search": web_search,
    **MCP_TOOL_MAP,
}

VISIBLE_TOOL_MAP = {
    "web_search": VisibleWebSearchModel,
}

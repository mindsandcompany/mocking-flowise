from .web_search import web_search, VisibleWebSearchModel, WEB_SEARCH


TOOL_MAP = {
    "web_search": web_search,
}

VISIBLE_TOOL_MAP = {
    "web_search": VisibleWebSearchModel,
}

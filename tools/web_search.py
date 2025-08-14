import aiohttp
import asyncio
import os
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Literal


class SingleSearchModel(BaseModel):
    q: str = Field(description="search string (use the language that's most likely to match the sources)")
    recency: int | None = Field(description="limit to recent N days, or null", default=None)
    domains: list[str] | None = Field(description="restrict to domains (e.g. [\"example.com\", \"another.com\"], or null)", default=None)


class MultipleSearchModel(BaseModel):
    search_query: list[dict] = Field(description="array of search query objects. You can call this tool with multiple search queries to get more results faster.")
    response_length: Literal["short", "medium", "long"] = Field(description="response length option", default="medium")


class VisibleWebSearchModel(BaseModel):
    node_label: str = "Visible Query Generator"
    
    @classmethod
    def format(cls, args: dict):
        queries = [sq['q'] for sq in args["search_query"]]
        return {
            "visible_web_search_query": queries
        }


WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_query": {
                    "type": "array",
                    "items": SingleSearchModel.model_json_schema(),
                    "description": "array of search query objects. You can call this tool with multiple search queries to get more results faster."
                },
                "response_length": {
                    "type": "string",
                    "enum": ["short", "medium", "long"],
                    "default": "medium",
                    "description": "response length option"
                }
            },
            "required": ["search_query"]
        }
    }
}


async def web_search(
    search_query: list[dict], 
    response_length: Literal["short", "medium", "long"]
) -> str:
    
    try:
        MultipleSearchModel.model_validate(locals())
        for sq in search_query:
            SingleSearchModel.model_validate(sq)
    except Exception as e:
        return f"Error validating `web_search`: {e}"

    async with aiohttp.ClientSession() as session:
        tasks = [single_search(session, sq.q, sq.recency, sq.domains, response_length) for sq in search_query]
        results = await asyncio.gather(*tasks)
    
    flatted_res = [item for sublist in results for item in sublist]
    output = [{'id': f'turn{idx}search{idx}', **item} for idx, item in enumerate(flatted_res)]
    
    return "\n".join([
        f'- {item["title"]} ({item["source"]}): {item["date"]} — {item["snippet"]} 【{item["id"]}】' if item['date'] else
        f'- {item["title"]} ({item["source"]}): {item["snippet"]} 【{item["id"]}】'
        for item in output
    ])


async def single_search(
    session: aiohttp.ClientSession, 
    q: str, 
    recency: str | None, 
    domains: list[str] | None, 
    response_length: Literal["short", "medium", "long"]
):
    url = "https://www.searchapi.io/api/v1/search"

    if domains:
        q = f"{q} site:{' OR site:'.join(domains)}"
    
    if response_length not in {"short", "medium", "long"}:
        raise ValueError("response_length must be 'short'|'medium'|'long'")
    
    size_map = {"short": 3, "medium": 5, "long": 7}
    
    num = size_map[response_length]
    params = {
        "engine": "google",
        "api_key": os.getenv("SEARCHAPI_KEY"),
        "q": q,
        "num": num
    }

    if recency:
        params["time_period_min"] = (datetime.now() - timedelta(days=recency)).strftime("%m/%d/%Y")

    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
        organic_results = data.get('organic_results', [])
        return [
            {
                "title": item['title'],
                "url": item['link'],
                "snippet": item['snippet'],
                "source": item['source'],
                "date": item.get("date", None)
            } for item in organic_results
        ]

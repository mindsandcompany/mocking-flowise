import aiohttp
import asyncio
import os
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Literal

from app.utils import States


class SingleSearchModel(BaseModel):
    q: str = Field(description="search string (use the language that's most likely to match the sources)")
    recency: int | None = Field(description="limit to recent N days, or null", default=None)
    domains: list[str] | None = Field(description='restrict to domains (e.g. ["example.com", "another.com"], or null)', default=None)


class MultipleSearchModel(BaseModel):
    search_query: list[SingleSearchModel] = Field(description="array of search query objects. You can call this tool with multiple search queries to get more results faster.")
    response_length: Literal["short", "medium", "long"] = Field(description="response length option", default="medium")


WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "search",
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
    states: States,
    **tool_input
) -> str:
    
    try:
        tool_input = MultipleSearchModel(**tool_input)
    except Exception as e:
        return f"Error validating `web_search`: {e}"

    async with aiohttp.ClientSession() as session:
        tasks = [
            single_search(
                session, 
                sq.q, 
                sq.recency, 
                sq.domains, 
                tool_input.response_length
            ) for sq in tool_input.search_query
        ]
        results = await asyncio.gather(*tasks)
    
    flatted_res = [item for sublist in results for item in sublist]
    
    outputs = []
    for idx, item in enumerate(flatted_res):
        id = f'{states.turn}:{idx}'
        states.tool_state.id_to_url[id] = item['url']
        outputs.append({'id': id, **item})
    
    states.turn += 1
    
    return "\n".join([
        f'- 【{item["id"]}†{item["title"]}†{item["source"]}】: {item["date"]} — {item["snippet"]}' if item['date'] else
        f'- 【{item["id"]}†{item["title"]}†{item["source"]}】: {item["snippet"]}'
        for item in outputs
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

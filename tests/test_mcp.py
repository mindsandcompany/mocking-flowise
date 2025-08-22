import asyncio
import aiohttp
import os
import requests
from dotenv import load_dotenv
load_dotenv("app/.env")


async def call_mcp_tool(server_id, tool_name, **tool_input):
        async with aiohttp.ClientSession() as session:
            token_response = await session.post(
                "https://genos.mnc.ai:3443/api/admin/auth/login",
                json={
                    "user_id": os.getenv("GENOS_ID"),
                    "password": os.getenv("GENOS_PW")
                }
            )
            token_response.raise_for_status()
            token = (await token_response.json())["data"]["access_token"]
            response = await session.post(
                f"https://genos.mnc.ai:3443/api/admin/mcp/server/test/{server_id}/tools/call",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                json={"tool_name": tool_name, "input_schema": tool_input}
            )
            response.raise_for_status()
            return await response.json()


def get_tools_description(server_id: str):
    token_response = requests.post(
        "https://genos.mnc.ai:3443/api/admin/auth/login",
        json={
            "user_id": os.getenv("GENOS_ID"),
            "password": os.getenv("GENOS_PW")
        }
    )
    token_response.raise_for_status()
    token = token_response.json()["data"]["access_token"]
    response = requests.get(
        f"https://genos.mnc.ai:3443/api/admin/mcp/server/test/{server_id}/tools",
        headers={
            "Authorization": f"Bearer {token}"
        }
    )
    response.raise_for_status()
    return response.json()['data']


if __name__ == "__main__":
    data = asyncio.run(call_mcp_tool("85", "open_url", opens=[{"url": "https://www.google.com"}]))
    # data = asyncio.run(call_mcp_tool("85", "web_search", search_query=[{"q": "apple", "recency": None, "domains": None}, {"q": "banana", "recency": None, "domains": None}], response_length="medium"))
    # data = asyncio.run(call_mcp_tool("83", "company_info", symbols=["005930", "AAPL"]))
    # data = asyncio.run(call_mcp_tool("83", "market_indicators", symbol="KOSPI", country="kr", date_from="2025-08-11", date_to="2025-08-13"))
    # data = asyncio.run(call_mcp_tool("83", "single_stock_price", symbol="NASDAQ:AAPL", date_from="2025-08-11", date_to="2025-08-13"))
    # data = get_tools_description("83")
    print(data)

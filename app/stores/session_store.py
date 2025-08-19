import os
import json
import datetime
from typing import List, Optional, Any

import redis.asyncio as redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class SessionStore:
    def __init__(self) -> None:
        self.client = redis.from_url(REDIS_URL, decode_responses=True)

    async def get_messages(self, chat_id: str) -> Optional[List[dict]]:
        raw = await self.client.get(f"chat:{chat_id}")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload.get("messages", None)

    async def save_messages(self, chat_id: str, messages: List[dict], ttl_seconds: int = 7 * 24 * 3600) -> None:
        payload = {
            "messages": messages,
            "updatedAt": datetime.datetime.utcnow().isoformat() + "Z",
        }
        data = json.dumps(payload, ensure_ascii=False)
        if ttl_seconds:
            await self.client.setex(f"chat:{chat_id}", ttl_seconds, data)
        else:
            await self.client.set(f"chat:{chat_id}", data)

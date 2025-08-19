import asyncio
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from utils import call_llm_stream, is_sse, ROOT_DIR, States
from stores.session_store import SessionStore
from tools import TOOL_MAP, VISIBLE_TOOL_MAP, WEB_SEARCH

router = APIRouter()
store = SessionStore()


class GenerateRequest(BaseModel):
    question: str
    chatId: str | None = None
    model_config = ConfigDict(extra='allow')


@router.post("/chat/stream")
async def chat_stream(req: GenerateRequest):
    queue: asyncio.Queue[str] = asyncio.Queue()
    SENTINEL = "__STREAM_DONE__"

    async def emit(event: str, data):
        payload = {"event": event, "data": data}
        await queue.put(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            await queue.put(": keep-alive\n\n")

    async def runner():
        try:
            chat_id = req.chatId or uuid4().hex

            system_prompt = (ROOT_DIR / "prompts" / "system.txt").read_text(encoding="utf-8").format(
                current_date=datetime.now().strftime("%Y-%m-%d"),
                locale="ko-KR"
            )

            states = States()
            persisted = await store.get_messages(chat_id)
            if persisted:
                history = [
                    *persisted,
                    {"role": "user", "content": req.question}
                ]
            else:
                history = [{"role": "user", "content": req.question}]
            
            states.messages = [
                {"role": "system", "content": system_prompt},
                *history
            ]
            states.tools = [WEB_SEARCH]

            while True:
                async for res in call_llm_stream(
                    messages=states.messages,
                    tools=states.tools,
                    temperature=0.2,
                ):
                    if is_sse(res):
                        await emit(res["event"], res["data"])
                    else:
                        states.messages.append(res)

                tool_calls = res.get("tool_calls")
                if not tool_calls:
                    break
                for tool_call in tool_calls:
                    tool_name = tool_call['function']['name']
                    tool_args = json.loads(tool_call['function']['arguments'])
                    
                    try:
                        tool_res = TOOL_MAP[tool_name](states, **tool_args)
                        if tool_name in VISIBLE_TOOL_MAP:
                            node_label = VISIBLE_TOOL_MAP[tool_name].node_label
                            visible_res = VISIBLE_TOOL_MAP[tool_name].format(tool_args)
                            await emit("agentFlowExecutedData", {
                                "nodeLabel": node_label,
                                "data": {
                                    "output": {
                                        "content": json.dumps(visible_res, ensure_ascii=False)
                                    }
                                }
                            })
                        if asyncio.iscoroutine(tool_res):
                            tool_res = await tool_res
                    except Exception as e:
                        tool_res = f"Error calling {tool_name}: {e}\n\nTry again with different arguments."
                    
                    states.messages.append({"role": "tool", "content": tool_res, "tool_call_id": tool_call['id']})

        except Exception as e:
            await emit("error", str(e))
        finally:
            last_message = states.messages[-1]
            history.append(last_message)
            await store.save_messages(chat_id, history)
            await emit("result", None)
            await queue.put(SENTINEL)

    async def sse():
        producer = asyncio.create_task(runner())
        pinger = asyncio.create_task(heartbeat())
        try:
            while True:
                chunk = await queue.get()
                if chunk == SENTINEL:
                    break
                yield chunk
        finally:
            producer.cancel()
            pinger.cancel()

    return StreamingResponse(
        sse(), 
        media_type="text/event-stream", 
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    ) 
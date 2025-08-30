import asyncio
import json
import os
import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.utils import (
    call_llm_stream, 
    is_sse, 
    is_valid_model, 
    ROOT_DIR, 
    States
)
from app.stores.session_store import SessionStore
from app.tools import get_tool_map, get_tools_for_llm
from app.logger import get_logger

router = APIRouter()
store = SessionStore()
log = get_logger(__name__)


class GenerateRequest(BaseModel):
    question: str
    chatId: str | None = None
    userInfo: dict | None = None
    model_config = ConfigDict(extra='allow')


@router.post("/chat/stream")
async def chat_stream(
    req: GenerateRequest, 
    request: Request
) -> StreamingResponse:
    """
    SSE 프로토콜을 사용하여 채팅 스트리밍을 제공합니다.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()
    SENTINEL = "__STREAM_DONE__"
    client_disconnected = asyncio.Event()

    async def emit(event: str, data):
        payload = {"event": event, "data": data}
        await queue.put(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

    async def heartbeat():
        while True:
            if client_disconnected.is_set():
                break
            await asyncio.sleep(10)
            await queue.put(": keep-alive\n\n")

    async def runner():
        try:
            states = States()
            chat_id = req.chatId or uuid4().hex
            log.info("chat stream started", extra={"chat_id": chat_id})

            if req.userInfo:
                states.user_id = req.userInfo.get("id")

            system_prompt = (ROOT_DIR / "prompts" / "system.txt").read_text(encoding="utf-8").format(
                current_date=datetime.now().strftime("%Y-%m-%d"),
                locale="ko-KR"
            )

            model = os.getenv("DEFAULT_MODEL")
            llm_regex = re.compile(r"<llm>(.*?)</llm>")
            llm_match = llm_regex.search(req.question)
            if llm_match:
                log.info("model override detected", extra={"chat_id": chat_id, "model": model})
                model = llm_match.group(1)
                if not is_valid_model(model):
                    model = os.getenv("DEFAULT_MODEL")
                    log.warning("model not found", extra={"chat_id": chat_id, "model": model})
                req.question = llm_regex.sub("", req.question).strip()
            
            if states.user_id:
                model_set_context_list = await store.get_messages(states.user_id)
                if model_set_context_list:
                    model_set_context = [{
                            "role": "system",
                            "content": "### User Memory\n" + "\n".join([f"{idx}. {msc}" for idx, msc in enumerate(model_set_context_list,   start=1)])
                        }]
                else:
                    model_set_context = []
            
            persisted = (await store.get_messages(chat_id)) or []
            history = [
                *persisted,
                {"role": "user", "content": req.question}
            ]
            
            states.messages = [
                {"role": "system", "content": system_prompt},
                *model_set_context,
                *history
            ]
            states.tools = await get_tools_for_llm()
            tool_map = await get_tool_map()

            while True:
                if client_disconnected.is_set():
                    break
                await emit("tool_state", states.tool_state.model_dump())
                async for res in call_llm_stream(
                    messages=states.messages,
                    tools=states.tools,
                    temperature=0.2,
                    model=model
                ):
                    if is_sse(res):
                        await emit(res["event"], res["data"])
                    else:
                        states.messages.append(res)

                tool_calls = res.get("tool_calls")
                contents = res.get("content")
                # 툴 호출이 없고 콘텐츠가 있으면 종료
                if not tool_calls and contents:
                    break
                # 툴 호출이 없고 콘텐츠가 없으면 다시 인퍼런스 시도
                elif not tool_calls and not contents:
                    continue
                # 툴 호출이 있으면 툴 호출 처리
                for tool_call in tool_calls:
                    tool_name = tool_call['function']['name']
                    tool_args = json.loads(tool_call['function']['arguments'])
                    log.info("tool call", extra={"chat_id": chat_id, "tool_name": tool_name})
                    
                    try:
                        tool_res = tool_map[tool_name](states, **tool_args)
                        if tool_name == "search":
                            await emit("agentFlowExecutedData", {
                                "nodeLabel": "Visible Query Generator",
                                "data": {
                                    "output": {
                                        "content": json.dumps({
                                            "visible_web_search_query": [sq['q'] for sq in tool_args['search_query']]
                                        }, ensure_ascii=False)
                                    }
                                }
                            })
                        elif tool_name == "open":
                            try:
                                if tool_args.get('id') and tool_args['id'].startswith('http'):
                                    url = tool_args['id']
                                elif tool_args.get('id') is None:
                                    url = getattr(states.tool_state, "current_url", None)
                                else:
                                    url = states.tool_state.id_to_url.get(tool_args['id'])
                                if url:
                                    await emit("agentFlowExecutedData", {
                                        "nodeLabel": "Visible URL",
                                        "data": {
                                            "output": {
                                                "content": json.dumps({
                                                    "visible_url": url
                                                }, ensure_ascii=False)
                                            }
                                        }
                                    })
                            except Exception as e:
                                pass

                        if asyncio.iscoroutine(tool_res):
                            tool_res = await tool_res
                    except Exception as e:
                        log.exception("tool call failed", extra={"chat_id": chat_id, "tool_name": tool_name})
                        tool_res = f"Error calling {tool_name}: {e}\n\nTry again with different arguments."
                    
                    states.messages.append({"role": "tool", "content": str(tool_res), "tool_call_id": tool_call['id']})

        except Exception as e:
            log.exception("chat stream failed")
            await emit("error", str(e))
            await emit("token", f"\n\n오류가 발생했습니다: {e}")
        finally:
            last_message = states.messages[-1]
            
            if isinstance(last_message, dict) and last_message.get("role") == "assistant":
                content = last_message.get("content", "")
                if isinstance(content, str):
                    content = re.sub(r"【[^】]*】", "", content).strip()
                    last_message = {**last_message, "content": content}
            
            history.append(last_message)
            await store.save_messages(chat_id, history)
            await emit("result", None)
            await queue.put(SENTINEL)
            log.info("chat stream finished", extra={"chat_id": chat_id})

    async def sse():
        producer = asyncio.create_task(runner())
        pinger = asyncio.create_task(heartbeat())
        try:
            while True:
                if await request.is_disconnected():
                    client_disconnected.set()
                    break
                chunk = await queue.get()
                if chunk == SENTINEL:
                    break
                yield chunk
        finally:
            client_disconnected.set()
            producer.cancel()
            pinger.cancel()

    return StreamingResponse(
        sse(), 
        media_type="text/event-stream", 
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )

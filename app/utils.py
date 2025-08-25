import os
import pathlib
import sys
from typing import Any
from pydantic import BaseModel, Field

from openai import AsyncOpenAI

ROOT_DIR = pathlib.Path(__file__).parent.absolute()


try:
    CLIENT = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
except Exception as e:
    print("오류: OPENROUTER_API_KEY 환경 변수가 설정되지 않았습니다.")
    print("환경 변수를 설정하거나 .env 파일에 추가해주세요.")
    sys.exit(1)


class ToolState(BaseModel):
    id_to_url: dict[str, str] = Field(default_factory=dict)
    url_to_page: dict[str, object] = Field(default_factory=dict)
    current_url: str | None = None
    tool_results: dict[str, object] = Field(default_factory=dict)
    id_to_iframe: dict[str, str] = Field(default_factory=dict)


class States:
    messages: list[dict]
    turn: int = 0
    tools: list[dict] = []
    tool_state: ToolState = ToolState()
    tool_results: dict[str, object] = {}


async def call_llm_stream(
    messages: list[dict], 
    model: str = os.getenv("DEFAULT_MODEL"), 
    **kwargs
):
    response = await CLIENT.chat.completions.create(
        messages=messages,
        model=model,
        stream=True,
        **kwargs
    )

    # Buffers to assemble the final message
    full_content_parts: list[str] = []
    full_reasoning_parts: list[str] = []
    tool_call_buf: dict[int, dict] = {}

    # Stream chunks
    async for chunk in response:
        choice = chunk.choices[0]
        delta = choice.delta

        # Reasoning tokens (stream + buffer)
        if getattr(delta, "reasoning", None):
            reasoning_piece = (delta.reasoning or "")
            if reasoning_piece:
                full_reasoning_parts.append(reasoning_piece)
                yield {
                    "event": "reasoning_token",
                    "data": reasoning_piece,
                }

        # Tool calls (buffer only; do not stream content alongside tool calls)
        if getattr(delta, "tool_calls", None):
            for i, tc in enumerate(delta.tool_calls):
                key = getattr(tc, "index", i)
                buf = tool_call_buf.setdefault(key, {
                    "id": None,
                    "type": "function",
                    "function": {"name": None, "arguments": ""},
                })
                # id may appear incrementally
                if getattr(tc, "id", None):
                    buf["id"] = tc.id
                # function name / arguments may arrive incrementally
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        buf["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        buf["function"]["arguments"] += fn.arguments or ""

        # Content tokens: stream only when there is no tool_call in this delta
        if not getattr(delta, "tool_calls", None) and getattr(delta, "content", None):
            content_piece = delta.content or ""
            if content_piece:
                full_content_parts.append(content_piece)
                yield {
                    "event": "token",
                    "data": content_piece,
                }

    # Build final assistant message object
    final_message: dict[str, Any] = {
        "role": "assistant",
    }

    final_content = "".join(full_content_parts).strip()
    if final_content:
        final_message["content"] = final_content
    else:
        # Normalize to empty string when no content accumulated
        final_message["content"] = ""

    final_reasoning = "".join(full_reasoning_parts).strip()
    if final_reasoning:
        final_message["reasoning"] = final_reasoning

    if tool_call_buf:
        # Normalize buffered tool calls into OpenAI-compatible structure
        tool_calls = []
        for _, tc in sorted(tool_call_buf.items(), key=lambda x: x[0]):
            tool_calls.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            })
        final_message["tool_calls"] = tool_calls

    # Yield the complete message object at the end
    yield final_message


def is_sse(response):
    class SSE(BaseModel):
        event: str
        data: Any

    try:
        SSE.model_validate(response)
        return True
    except Exception:
        return False

import aiohttp, json, asyncio


async def main() -> dict:
    data = {
        "question": "영화 '84제곱미터'의 젊은 남자 주연배우의 데뷔작의 방송 횟수는?"
    }
    endpoint = "http://0.0.0.0:6666/chat/stream"

    result = {}
    text_acc = ""

    BIG = 2**30
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None),
        read_bufsize=BIG, max_line_size=BIG
    ) as session:
        async with session.post(endpoint, json=data, headers={
            "x-request-from":"internal",
            "Accept": "text/event-stream"
        }) as resp:
            reasoning = ""
            async for line in resp.content:
                if not line:
                    continue
                decoded = line.decode("utf-8").strip()
                if decoded.startswith("data:"):
                    decoded = decoded.removeprefix("data:")
                try:
                    payload = json.loads(decoded)
                except json.JSONDecodeError:
                    continue

                event = payload.get("event")
                ev_data = payload.get("data")

                if event == "reasoning_token":
                    reasoning += ev_data
                elif reasoning:
                    result.setdefault('agentFlowExecutedData', []).append({
                        "nodeLabel": "Visible Reasoner",
                        "data": {"output": {"content": json.dumps({"visible_rationale": reasoning}, ensure_ascii=False)}}
                    })
                    reasoning = ""
                    print("agentFlowExecutedData")
                    print(result['agentFlowExecutedData'])
                    print("="*100)
                    
                if event == "token":
                    if isinstance(ev_data, str):
                        text_acc += ev_data
                    print(ev_data, flush=True, end="")
                elif event == "agentFlowExecutedData":
                    result.setdefault('agentFlowExecutedData', []).append(ev_data)
                    print("agentFlowExecutedData")
                    print(result['agentFlowExecutedData'])
                    print("="*100)
                elif event == "error":
                    result["message"] = ev_data
                    result["success"] = False
                    result['statusCode'] = 500
                elif event == "result":
                    # 토큰만 왔다가 최종 result가 없으면 text로 보강
                    if text_acc and "text" not in result:
                        result["text"] = text_acc
                    print("result")
                    print(result)
                    print("="*100)

    # 워크플로우 다음 스텝으로 넘길 데이터 머지 후 반환
    data.update(result)
    return data


if __name__ == "__main__":
    asyncio.run(main())

import aiohttp, json, asyncio
import re
from urllib.parse import urlparse


async def main() -> dict:
    data = {
        "question": "삼성전자의 2025년 1분기 영업이익 발표 당일, 코스피 지수 상승률은 몇 퍼센트인가?",
        # "chatID": "qwer1234"
    }
    endpoint = "http://0.0.0.0:5555/chat/stream"

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
            tool_state = None
            citation_buffer = ""
            inside_citation = False

            def replace_citation_segment(segment: str) -> str:
                # segment: "【...】" 형태. 내부의 turn:id 만 URL로 치환하고 나머지는 제거
                try:
                    if not (segment.startswith("【") and segment.endswith("】")):
                        return segment
                    body = segment[1:-1]
                    ids = re.findall(r"(\d+:\d+)", body)
                    if not ids:
                        return ""
                    id_to_url = {}
                    if isinstance(tool_state, dict):
                        id_to_url = tool_state.get("id_to_url", {}) or {}
                    mapped = [id_to_url.get(idv, idv) for idv in ids]
                    
                    def get_domain_without_lib(url):
                        try:
                            # 1. URL 파싱하여 'netloc' (도메인 부분) 추출
                            parsed_url = urlparse(url)
                            domain = parsed_url.netloc

                            # 2. 'www.'가 있다면 제거
                            if domain.startswith('www.'):
                                domain = domain[4:]
                                
                            return domain
                        except Exception:
                            return "link"
                    
                    styled = [
                        f'<a href="{url}" target="_blank" class="btn__chip"> <strong>{get_domain_without_lib(url)}</strong></a>'
                        for url in mapped
                    ]
                    return " ".join(styled)
                except Exception:
                    return segment

            def process_token(ev_text: str):
                nonlocal citation_buffer, inside_citation, text_acc
                i = 0
                n = len(ev_text)
                while i < n:
                    if inside_citation:
                        citation_buffer += ev_text[i]
                        i += 1
                        # 버퍼에 닫힘이 생기면 한 세그먼트 처리
                        close_idx = citation_buffer.find("】")
                        if close_idx != -1:
                            segment = citation_buffer[:close_idx+1]
                            remainder = citation_buffer[close_idx+1:]
                            try:
                                if re.fullmatch(r"【\d+†chart】", segment):
                                    key = segment[1:-1]
                                    id_to_iframe = {}
                                    if isinstance(tool_state, dict):
                                        id_to_iframe = tool_state.get("id_to_iframe", {}) or {}
                                    replaced = id_to_iframe.get(key, "")
                                else:
                                    replaced = replace_citation_segment(segment)
                            except Exception:
                                replaced = ""
                            text_acc += replaced
                            print(replaced, flush=True, end="")
                            citation_buffer = ""
                            inside_citation = False
                            if remainder:
                                # remainder 내에 추가 인용이 있을 수 있으므로 재귀적으로 처리
                                process_token(remainder)
                            # 이 케이스는 remainder 처리까지 끝났으므로 루프 계속
                    else:
                        # 인용 시작 찾기
                        start_idx = ev_text.find("【", i)
                        if start_idx == -1:
                            chunk = ev_text[i:]
                            if chunk:
                                text_acc += chunk
                                print(chunk, flush=True, end="")
                            break
                        # 인용 시작 전 일반 텍스트 출력
                        if start_idx > i:
                            chunk = ev_text[i:start_idx]
                            text_acc += chunk
                            print(chunk, flush=True, end="")
                        # 인용 시작부터 버퍼링 시작
                        inside_citation = True
                        citation_buffer = "【"
                        i = start_idx + 1
                # 루프 종료. 인용 중이면 계속 버퍼링 상태 유지

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

                if event == "tool_state":
                    tool_state = ev_data
                elif event == "reasoning_token":
                    reasoning += ev_data
                elif reasoning:
                    result.setdefault('agentFlowExecutedData', []).append({
                        "nodeLabel": "Visible Reasoner",
                        "data": {"output": {"content": json.dumps({"visible_rationale": reasoning}, ensure_ascii=False)}}
                    })
                    print()
                    print("🧠 Thinking...")
                    print(reasoning)
                    print("="*100)
                    reasoning = ""
                    
                if event == "token":
                    if isinstance(ev_data, str):
                        process_token(ev_data)
                elif event == "agentFlowExecutedData":
                    result.setdefault('agentFlowExecutedData', []).append(ev_data)
                    if ev_data.get("nodeLabel") == "Visible Reasoner":
                        reasoning = json.loads(ev_data.get("data", {}).get("output", {}).get("content", "")).get("visible_rationale", "")
                        print()
                        print("="*100)
                        print("🧠 Thinking...")
                        print(reasoning)
                        print()
                        print("="*100)
                    elif ev_data.get("nodeLabel") == "Visible URL":
                        url = json.loads(ev_data.get("data", {}).get("output", {}).get("content", "")).get("visible_url", "")
                        if url:
                            print()
                            print("="*100)
                            print("👀 Reading...")
                            print("🔗", url)
                            print()
                            print("="*100)
                    elif ev_data.get("nodeLabel") == "Visible Query Generator":
                        query = json.loads(ev_data.get("data", {}).get("output", {}).get("content", "")).get("visible_web_search_query", [])
                        if query:
                            print()
                            print("="*100)
                            print("🔍 Searching...")
                            print("     ".join([f"🔍 {q}" for q in query]))
                            print()
                            print("="*100)
                elif event == "error":
                    result["message"] = ev_data
                    result["success"] = False
                    result['statusCode'] = 500
                elif event == "result":
                    # 토큰만 왔다가 최종 result가 없으면 text로 보강
                    if text_acc and "text" not in result:
                        result["text"] = text_acc

    # 워크플로우 다음 스텝으로 넘길 데이터 머지 후 반환
    data.update(result)
    return data


if __name__ == "__main__":
    asyncio.run(main())

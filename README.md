# Mocking Flowise

## 개요
'Mocking Flowise'는 GenOS에 탑재된 flowise로는 어렵거나 비효율적인 기능에 대해서 코드로 직접 구현하고, 도커 및 FastAPI를 이용하여 flowise와 비슷한 역할을 하는 앱을 띄운 뒤 GenOS의 워크플로우와 연결하는 예제 프로젝트입니다. 기본적인 LLM 호출 및, 툴 호출 기능까지 구현되어있습니다.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" />
</p>

---

## 기능 요약
- LLM 스트리밍 응답(SSE) 지원: `token`, `reasoning_token`, `result`, `error` 이벤트 전송
- 툴 호출 지원: 예시로 `web_search`(searchapi.io 기반) 포함
- 툴 실행 내용을 GenOS 채팅 UI에 노출하기 위한 전용 이벤트(`agentFlowExecutedData`) 전송
- Docker로 손쉽게 배포 가능

## 디렉터리 구조
```text
mock_workflow/
  ├─ app.py                 # FastAPI 엔트리, SSE 스트리밍/툴 실행 흐름
  ├─ utils.py               # OpenRouter(OpenAI 호환) 클라이언트, 스트림 유틸
  ├─ tools/
  │   ├─ __init__.py        # TOOL_MAP, VISIBLE_TOOL_MAP 등록
  │   └─ web_search.py      # 웹 검색 툴 정의 및 보이는 정보 포맷 정의
  ├─ prompts/
  │   └─ system.txt         # 시스템 프롬프트
  ├─ requirements.txt
  ├─ Dockerfile
  └─ README.md
```

## 요구 사항
- Python 3.11+
- OpenRouter API Key (`OPENROUTER_API_KEY`)
- searchapi.io API Key (`SEARCHAPI_KEY`) — 웹 검색 툴 사용 시 필요

## 설치 및 실행

### 환경 변수 설정(`.env` 권장)
```bash
# .env 예시
OPENROUTER_API_KEY=<your_openrouter_api_key>
DEFAULT_MODEL=openai/gpt-4o-mini
SEARCHAPI_KEY=<your_searchapi_key>
PORT=6666
```

### Docker로 실행
```bash
# 이미지 빌드
docker build -t mocking-flowise .
# 컨테이너 실행
docker run -d --name mocking-flowise \
  -p 6666:6666 \
  mocking-flowise:latest
```

## SSE 이벤트 규칙 (GenOS 채팅 앱 표현 규칙)
- 본 프로젝트는 각 SSE 청크를 다음과 같은 JSON 한 줄로 보냅니다. 실제 SSE 라인은 아래 형식입니다.
  - `data: {"event": string, "data": any}` + 빈 줄
  - 주기적 하트비트: `: keep-alive` (클라이언트는 무시 가능)
- 이벤트 타입과 `data` 규칙
  - `token`: 모델의 일반 답변 토큰. `data`는 텍스트 조각(string)
  - `reasoning_token`: 모델의 추론(리저닝) 토큰. `data`는 텍스트 조각(string)
  - `agentFlowExecutedData`: 툴 실행 결과를 채팅 UI(에이전트 플로우 노드)에 노출하기 위한 이벤트
    - payload 예시:
      ```json
      {
        "event": "agentFlowExecutedData",
        "data": {
          "nodeLabel": "Visible Query Generator",
          "data": {
            "output": {
              "content": "{\"visible_web_search_query\":[\"python 3.12 change\"]}"
            }
          }
        }
      }
      ```
    - 중요: 이벤트가 `agentFlowExecutedData`인 경우에는 `data.data.output.content`에 GenOS 프론트와 [약속된 규칙](https://genos-docs.gitbook.io/default/advanced-tutorials/guides/workflow/research-agent/workflow-research-agent#convention-1)에 따른 내용이 들어있어야 GenOS 채팅 어플리케이션의 추론과정에 표현됩니다. 
  - `error`: 오류 메시지(string)
  - `result`: 최종 완료 신호. `data`는 `null`

## Workflow Python Step
GenOS 워크플로우의 Python Step을 생성한 후 아래 코드에서 endpoint를 바꾸어서 사용하시면 됩니다.
```Python
from main_socketio import sio_server
import aiohttp, json

async def run(data: dict) -> dict:
    sid = data.get('socketIOClientId')  # 프론트 소켓 ID
    endpoint = "<your-end-point>"
    result = {}
    text_acc = ""

    BIG = 2**30
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None),
        read_bufsize=BIG, max_line_size=BIG
    ) as session:
        async with session.post(endpoint, json=data, headers={"x-request-from":"internal"}) as resp:
            prev_event = None
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
                    if sid:
                        await sio_server.emit("agentFlowExecutedData", result['agentFlowExecutedData'], room=sid)
                
                if event == "token":
                    if isinstance(ev_data, str):
                        text_acc += ev_data
                    if sid:
                        await sio_server.emit("token", ev_data, room=sid)
                elif event == "agentFlowExecutedData":
                    result.setdefault('agentFlowExecutedData', []).append(ev_data)
                    if sid:
                        await sio_server.emit("agentFlowExecutedData", result['agentFlowExecutedData'], room=sid)
                elif event == "error":
                    result["message"] = ev_data
                    result["success"] = False
                    result['statusCode'] = 500
                elif event == "result":
                    # 토큰만 왔다가 최종 result가 없으면 text로 보강
                    if text_acc and "text" not in result:
                        result["text"] = text_acc
                    if sid:
                        await sio_server.emit("result", result, room=sid)
                
                prev_event = event

    # 워크플로우 다음 스텝으로 넘길 데이터 머지 후 반환
    data.update(result)
    return data
```

## 툴 사용 및 노출 규칙
- 툴 스키마: OpenAI 함수 호출 포맷을 따르며, 예시로 `web_search`가 등록되어 있습니다.
  - 등록 위치: `tools/web_search.py` 의 `WEB_SEARCH` 스키마, 실행 함수 `web_search()`
  - 서버 등록: `tools/__init__.py` 의 `TOOL_MAP` (실행), `VISIBLE_TOOL_MAP` (UI 노출)
- 사람이 볼 정보만 보이게 하기
  - 각 툴에 대응하는 `Visible*Model`을 정의하여 `format(args)`에서 공개 가능한 정보만 추립니다.
  - 서버는 `format(args)` 결과를 `json.dumps(...)`로 문자열화하여 `agentFlowExecutedData.data.data.output.content`에 넣어 보냅니다.
  - `nodeLabel`은 UI 노드명으로 사용됩니다.
- 새 툴 추가 가이드(요약)
  1) `tools/my_tool.py`에 실행 함수, `WEB_MY_TOOL` 스키마, `VisibleMyToolModel` 구현
  2) `tools/__init__.py`의 `TOOL_MAP`, `VISIBLE_TOOL_MAP`에 등록
  3) `app.py`의 `tools = [...]` 목록에 `WEB_MY_TOOL` 추가

---

## 주의사항
- 현재 멀티턴 구현은 안되어있습니다.
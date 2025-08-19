# Mocking Flowise

## 개요
'Mocking Flowise'는 GenOS에 탑재된 flowise로는 어렵거나 비효율적인 기능에 대해서 코드로 직접 구현하고, Docker 및 FastAPI를 이용하여 flowise와 유사한 역할을 하는 API를 제공한 뒤 GenOS의 워크플로우와 연결하는 예제 프로젝트입니다. 기본적인 LLM 스트리밍 호출(SSE)과 툴 호출 기능을 포함합니다.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" />
</p>

---

## 기능 요약
- LLM 스트리밍 응답(SSE) 지원: `token`, `reasoning_token`, `result`, `error` 이벤트 전송
- 툴 호출 지원: 예시로 `web_search`(searchapi.io 기반) 포함
- 툴 실행 내용을 GenOS 채팅 UI에 노출하기 위한 전용 이벤트(`agentFlowExecutedData`) 전송
- Docker/Compose로 손쉽게 실행 가능 (API + Redis)
- Redis 기반 멀티세션(chatId) 지원: `chatId`로 세션 저장/복구, 스트림 시작 시 `session` 이벤트로 `chatId` 알림

## 디렉터리 구조
```text
mock_workflow/
  ├─ app/
  │  ├─ __init__.py
  │  ├─ main.py                 # FastAPI 엔트리 및 라우터 포함
  │  ├─ api/
  │  │  ├─ __init__.py
  │  │  ├─ chat.py              # /chat/stream (SSE)
  │  │  └─ health.py            # /health
  │  ├─ prompts/
  │  │  └─ system.txt           # 시스템 프롬프트
  │  ├─ stores/
  │  │  ├─ __init__.py
  │  │  └─ session_store.py     # Redis 기반 세션 저장/복구
  │  ├─ tools/
  │  │  ├─ __init__.py          # TOOL_MAP, VISIBLE_TOOL_MAP 등록
  │  │  └─ web_search.py        # 웹 검색 툴 및 공개 포맷 정의
  │  ├─ utils.py                # OpenRouter 클라이언트, 스트림 유틸 등
  │  └─ .env                    # 주요한 환경변수 관리
  ├─ script/
  │  └─ docker-run.py            # 도커 빌드 및 실행 스크립트
  ├─ tests/
  │  └─ test_chat.py            # SSE 수신 예제 스크립트
  ├─ docker-compose.yml         # API(5555) + Redis 구성
  ├─ Dockerfile
  ├─ requirements.txt
  └─ README.md
```

## 요구 사항
- Python 3.11+
- OpenRouter API Key (`OPENROUTER_API_KEY`)
- searchapi.io API Key (`SEARCHAPI_KEY`) — 웹 검색 툴 사용 시 필요
- Redis 7.x (docker compose 사용 시 자동 구성, 로컬 실행 시 `REDIS_URL`로 연결)

## 환경 변수 (.env 권장)
```bash
# .env 예시
OPENROUTER_API_KEY=<your_openrouter_api_key>
DEFAULT_MODEL=openai/gpt-4o-mini
SEARCHAPI_KEY=<your_searchapi_key>
# 선택: 로컬 Redis를 쓸 때
# REDIS_URL=redis://localhost:6379/0
# 선택: 로컬 실행 포트 (기본 6666)
# PORT=6666
```

## 실행 방법

### 1) 로컬 실행 (개발용)
```bash
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)  # 또는 수동으로 환경 변수 설정
# 방법 A: 모듈 실행 (reload 포함)
python -m app.main
# 방법 B: uvicorn 직접 실행
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-6666} --reload
```
- 헬스체크: `curl -s http://localhost:${PORT:-6666}/health | cat`

### 2) Docker Compose (권장)
```bash
docker compose --env-file .env up -d --build
# 상태 확인
docker compose ps
# 헬스체크
curl -s http://localhost:5555/health | cat
```
- 컨테이너 기본 포트는 5555입니다. (Dockerfile `EXPOSE 5555` 및 Compose `5555:5555`)
- 코드/의존성/Dockerfile 변경 후에는 `--build`를 붙여 최신 상태로 반영하세요.

## 엔드포인트 요약
- `GET /health` — 단순 헬스체크
- `POST /chat/stream` — SSE 스트리밍 응답
  - 헤더 예시: `Accept: text/event-stream`
  - 요청 바디 예시: `{ "question": "...", "chatId": "옵션" }`

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

## 툴 사용 및 노출 규칙
- 툴 스키마: OpenAI 함수 호출 포맷을 따르며, 예시로 `web_search`가 등록되어 있습니다.
  - 등록 위치: `app/tools/web_search.py` 의 `WEB_SEARCH` 스키마, 실행 함수 `web_search()`
  - 서버 등록: `app/tools/__init__.py` 의 `TOOL_MAP` (실행), `VISIBLE_TOOL_MAP` (UI 노출)
  - 서버 사용: `app/api/chat.py`에서 `states.tools = [WEB_SEARCH]`로 사용
- 사람이 볼 정보만 노출하기
  - 각 툴에 대응하는 `Visible*Model`을 정의하여 `format(args)`에서 공개 가능한 정보만 추립니다.
  - 서버는 `format(args)` 결과를 `json.dumps(...)`로 문자열화하여 `agentFlowExecutedData.data.data.output.content`에 넣어 보냅니다.
  - `nodeLabel`은 UI 노드명으로 사용됩니다.
- 새 툴 추가 가이드(요약)
  1) `app/tools/my_tool.py`에 실행 함수, 스키마 `WEB_MY_TOOL`, 공개 모델 `VisibleMyToolModel` 구현
  2) `app/tools/__init__.py`의 `TOOL_MAP`, `VISIBLE_TOOL_MAP`에 등록
  3) `app/api/chat.py`의 `states.tools`에 `WEB_MY_TOOL` 추가

## Workflow Python Step (예시)
GenOS 워크플로우의 Python Step을 생성한 후 아래 코드에서 `endpoint`를 여러분의 배포 주소로 바꾸어 사용하시면 됩니다. (소켓 관련 로직은 사용 환경에 맞게 조정하세요.)
```python
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

---

## 주의사항
- 멀티턴/멀티세션 지원: `POST /chat/stream`에 `chatId`를 주면 해당 세션을 이어서 대화합니다. `chatId`가 없으면 서버가 생성하며 스트림 초기에 `session` 이벤트로 전달합니다.
- 세션 저장: Redis에 `chat:{chatId}` 키로 저장되며 기본 TTL은 7일입니다.
- 동시성: 동일 `chatId`로 동시 요청 시 단순히 마지막 저장이 우선합니다(필요 시 분산 락/트랜잭션으로 강화 가능).
"""공용 HTTP 클라이언트.

[이 파일이 왜 있냐]
- TourAPI 호출은 외부 의존이라 일시 장애가 흔함 → 자동 재시도가 필수
- timeout 일관 적용 (오래 매달리면 잡 전체가 멈춤)
- httpx는 모던 비동기 HTTP 클라이언트. requests의 async 버전 같은 것.
"""

from __future__ import annotations

import httpx
from tenacity import (  # tenacity = 재시도 라이브러리
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _should_retry_http_status(exc: BaseException) -> bool:
    """HTTP 상태코드 중 재시도할 값(429, 5xx)만 선별."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    return status == 429 or 500 <= status < 600


def build_http_client() -> httpx.AsyncClient:
    """공용 비동기 HTTP 클라이언트 생성.

    - timeout=10초 (TourAPI는 보통 1~3초, 10초 넘으면 비정상)
    - http2=False (TourAPI 서버 호환성)
    - 호출자가 close 책임. 보통 `async with build_http_client() as client:` 형태로 사용.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        http2=False,
    )

# 데코레이터 — 함수 정의 위에 @ 붙이면 "이 함수 호출에 자동 재시도 입혀줘"
@retry(
    stop=stop_after_attempt(3),                         # 최대 3번 시도 (원본 + 재시도 2번)
    wait=wait_exponential(multiplier=1, min=1, max=8),  # 1초, 2초, 4초 식 백오프
    retry=(
        retry_if_exception_type((                        # 어떤 예외에 재시도할지
            httpx.TransportError,    # 네트워크 끊김 등
            httpx.ReadTimeout,       # 읽기 타임아웃
            httpx.RemoteProtocolError,
        ))
        | retry_if_exception(_should_retry_http_status)  # 429/5xx만 재시도
    ),
    reraise=True,                # 다 실패하면 마지막 예외 그대로 던짐
)
async def get_json(client: httpx.AsyncClient, url: str, params: dict[str, str]) -> dict:
    """GET 요청 → JSON 파싱 (재시도 포함).

    HTTP 상태가 4xx/5xx면 `raise_for_status()`가 예외를 던진다.
    재시도 가치가 없는 4xx (예: 잘못된 키) 는 즉시 위로 전파.
    """
    response = await client.get(url, params=params)
    response.raise_for_status()  # 200 아니면 예외
    return response.json()

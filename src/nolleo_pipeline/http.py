"""httpx 비동기 클라이언트와 재시도 래퍼."""

from httpx import AsyncClient

# TODO: timeout/retry 정책을 운영 문서 기준으로 세분화
# TODO: 공통 query/header 주입


def build_http_client() -> AsyncClient:
    """공용 HTTP 클라이언트를 생성한다."""
    raise NotImplementedError


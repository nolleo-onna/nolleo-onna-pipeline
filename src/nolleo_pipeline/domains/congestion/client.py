"""혼잡도 API 동기화 클라이언트."""


class CongestionApiClient:
    """혼잡도 API 엔드포인트 호출."""

    async def list(self, page: int, num_of_rows: int):
        # TODO: 목록 API 호출
        raise NotImplementedError

    async def fetch_full(self, content_id: str):
        # TODO: 상세 API 호출
        raise NotImplementedError

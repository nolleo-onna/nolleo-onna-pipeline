"""기상청 API 동기화 클라이언트."""


class KmaWeatherClient:
    """기상청 API 엔드포인트 호출."""

    async def list(self, page: int, num_of_rows: int) -> None:
        # TODO: 목록 API 호출
        raise NotImplementedError

    async def fetch_full(self, base_time: str) -> None:
        # TODO: 상세 API 호출
        raise NotImplementedError

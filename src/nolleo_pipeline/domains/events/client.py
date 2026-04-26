"""TourAPI 행사 동기화 클라이언트."""


class TourApiEventClient:
    """TourAPI 행사 엔드포인트 호출."""

    async def list(self, page: int, num_of_rows: int):
        # TODO: 목록 API 호출
        raise NotImplementedError

    async def fetch_full(self, content_id: str, content_type_id: str):
        # TODO: 상세 API 병렬 호출
        raise NotImplementedError

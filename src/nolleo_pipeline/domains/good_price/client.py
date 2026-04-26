"""부산 공공데이터 착한가격업소 동기화 클라이언트."""


class BusanGoodPriceClient:
    """착한가격업소 API 엔드포인트 호출."""

    async def list(self, page: int, num_of_rows: int):
        # TODO: 목록 API 호출
        raise NotImplementedError

    async def fetch_full(self, item_id: str):
        # TODO: 상세 API 호출
        raise NotImplementedError

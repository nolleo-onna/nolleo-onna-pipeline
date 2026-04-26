"""TourAPI 관광지 동기화 클라이언트."""


class TourApiSpotClient:
    """TourAPI 관광지 엔드포인트 호출."""

    async def list_by_area(self, area_code: str, page: int, num_of_rows: int):
        """지역별 관광지 목록을 조회한다."""
        # TODO: areaBasedList2 호출
        raise NotImplementedError

    async def fetch_full(self, content_id: str, content_type_id: str):
        """관광지 상세 데이터를 조회한다."""
        # TODO: detailCommon2/Intro2/Info2/Image2 병렬 호출
        raise NotImplementedError


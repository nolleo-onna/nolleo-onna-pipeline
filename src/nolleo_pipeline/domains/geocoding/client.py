"""지오코딩 API 동기화 클라이언트."""


class GeocodingClient:
    """지오코딩 API 엔드포인트 호출."""

    async def geocode(self, address: str) -> None:
        # TODO: 주소 -> 좌표 변환 API 호출
        raise NotImplementedError

    async def reverse_geocode(self, lat: float, lng: float) -> None:
        # TODO: 좌표 -> 주소 변환 API 호출
        raise NotImplementedError

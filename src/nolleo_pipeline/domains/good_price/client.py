"""부산 음식/가격 공공데이터 동기화 클라이언트."""
from __future__ import annotations

from typing import Any

import httpx

from nolleo_pipeline.common.http import get_json


class PublicDataPageClient:
    """공공데이터포털 pageNo/numOfRows 방식 API 호출."""

    def __init__(self, http: httpx.AsyncClient, *, service_key: str, endpoint_url: str) -> None:
        self._http = http
        self._service_key = service_key
        self._endpoint_url = endpoint_url

    async def list_page(self, *, page: int, num_of_rows: int) -> dict[str, Any]:
        """공공데이터포털 1페이지 조회."""
        params = {
            "serviceKey": self._service_key,
            "ServiceKey": self._service_key,
            "pageNo": str(page),
            "numOfRows": str(num_of_rows),
            "resultType": "json",
            "_type": "json",
        }
        return await get_json(self._http, self._endpoint_url, params)


class OdcloudDatasetClient:
    """공공데이터포털 odcloud page/perPage 방식 API 호출."""

    def __init__(self, http: httpx.AsyncClient, *, service_key: str, endpoint_url: str) -> None:
        self._http = http
        self._service_key = service_key
        self._endpoint_url = endpoint_url

    async def list_page(self, *, page: int, per_page: int) -> dict[str, Any]:
        """odcloud 데이터셋 1페이지 조회."""
        params = {
            "serviceKey": self._service_key,
            "page": str(page),
            "perPage": str(per_page),
            "returnType": "JSON",
        }
        return await get_json(self._http, self._endpoint_url, params)


class BusanGoodPriceClient(PublicDataPageClient):
    """이전 이름 호환용 착한가격업소 클라이언트."""

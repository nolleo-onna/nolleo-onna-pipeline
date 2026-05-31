"""TourAPI 여행코스 동기화 클라이언트.

[이 파일이 왜 있냐]
- TourAPI 호출 로직(URL/파라미터/에러 처리)을 한 곳에 모아 일관성을 유지한다.
- 목록 조회와 상세 endpoint 병렬 호출을 분리해 파이프라인 가독성을 높인다.
- httpx.AsyncClient 주입 방식으로 커넥션 풀 재사용/테스트 대체를 쉽게 만든다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from nolleo_pipeline.common.http import get_json

TOURAPI_BASE_URL = "https://apis.data.go.kr/B551011/KorService2"
LIST_ENDPOINT = "/areaBasedList2"
DETAIL_ENDPOINTS = ("detailCommon2", "detailIntro2", "detailInfo2", "detailImage2")
_DETAIL_PAGE_PARAMS = {"numOfRows": "10", "pageNo": "1"}


class TourApiTravelCourseClient:
    """TourAPI 여행코스 endpoint 호출 모음."""

    def __init__(self, http_client: httpx.AsyncClient, service_key: str) -> None:
        self._http = http_client
        self._service_key = service_key

    async def list(
        self,
        *,
        l_dong_regn_cd: str,
        page: int,
        num_of_rows: int,
    ) -> dict[str, Any]:
        """areaBasedList2: 여행코스(contentTypeId=25) 목록 조회."""
        params = self._base_params() | {
            "lDongRegnCd": l_dong_regn_cd,
            "contentTypeId": "25",
            "pageNo": str(page),
            "numOfRows": str(num_of_rows),
            "arrange": "C",
        }
        return await self._get(LIST_ENDPOINT, params)

    async def fetch_full(
        self,
        *,
        content_id: str,
        content_type_id: str = "25",
    ) -> dict[str, dict[str, Any]]:
        """detail 4종 병렬 호출."""
        results = await asyncio.gather(
            self._fetch_detail("detailCommon2", content_id, content_type_id),
            self._fetch_detail("detailIntro2", content_id, content_type_id),
            self._fetch_detail("detailInfo2", content_id, content_type_id),
            self._fetch_detail_image(content_id),
        )
        return dict(zip(DETAIL_ENDPOINTS, results, strict=True))

    async def _fetch_detail(
        self,
        endpoint: str,
        content_id: str,
        content_type_id: str,
    ) -> dict[str, Any]:
        params = self._base_params() | _DETAIL_PAGE_PARAMS | {"contentId": content_id}
        if endpoint != "detailCommon2":
            params["contentTypeId"] = content_type_id
        payload = await self._get(f"/{endpoint}", params)
        # detailInfo2는 코스 하위 item이 여러 건이므로 원본 payload를 보존한다.
        # _extract_first_item()을 거치면 첫 항목만 남아 코스 순서 정보가 유실된다.
        if endpoint == "detailInfo2":
            return payload
        return _extract_first_item(payload)

    async def _fetch_detail_image(self, content_id: str) -> dict[str, Any]:
        params = self._base_params() | _DETAIL_PAGE_PARAMS | {
            "contentId": content_id,
            "imageYN": "Y",
        }
        return await self._get("/detailImage2", params)

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        payload = await get_json(self._http, f"{TOURAPI_BASE_URL}{path}", params)
        _raise_on_tourapi_error(payload)
        return payload

    def _base_params(self) -> dict[str, str]:
        return {
            "serviceKey": self._service_key,
            "MobileOS": "ETC",
            "MobileApp": "nolleo-onna",
            "_type": "json",
        }


def _extract_first_item(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items")
    if not isinstance(items, dict):
        return {}
    item = items.get("item")
    if isinstance(item, list):
        return item[0] if item and isinstance(item[0], dict) else {}
    if isinstance(item, dict):
        return item
    return {}


def _raise_on_tourapi_error(payload: dict[str, Any]) -> None:
    result_code: str | None = None
    result_msg: str | None = None

    response = payload.get("response")
    if isinstance(response, dict):
        header = response.get("header")
        if isinstance(header, dict):
            code = header.get("resultCode")
            msg = header.get("resultMsg")
            result_code = str(code) if code is not None else None
            result_msg = str(msg) if msg is not None else None

    if result_code is None:
        code = payload.get("resultCode")
        msg = payload.get("resultMsg")
        result_code = str(code) if code is not None else None
        result_msg = str(msg) if msg is not None else None

    if result_code is not None and result_code != "0000":
        raise ValueError(
            f"TourAPI error: resultCode={result_code}, resultMsg={result_msg or 'unknown'}"
        )
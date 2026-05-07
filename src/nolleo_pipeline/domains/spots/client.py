"""TourAPI 관광지 동기화 클라이언트.

[이 파일이 왜 있냐]
- TourAPI를 호출하는 코드 한 군데에 모음 (URL/파라미터 형식 일관 관리)
- 4개 endpoint 병렬 호출로 latency 줄임 (4번 sequential = 느림)
- httpx.AsyncClient는 호출자가 주입 (테스트/풀 재사용 위해)
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from nolleo_pipeline.common.http import get_json

TOURAPI_BASE_URL = "https://apis.data.go.kr/B551011/KorService2"

LIST_ENDPOINT = "/areaBasedList2"
DETAIL_ENDPOINTS = ("detailCommon2", "detailIntro2", "detailInfo2", "detailImage2")

# 매뉴얼 v4.4의 모든 detail 예시 URL에 numOfRows/pageNo가 포함됨.
# 스펙 표기는 옵션이지만 strict하게 받는 케이스가 있어 기본값으로 항상 보낸다.
_DETAIL_PAGE_PARAMS = {"numOfRows": "10", "pageNo": "1"}


class TourApiSpotClient:
    """TourAPI 관광지 endpoint 호출 모음.

    사용 예:
        async with build_http_client() as http:
            client = TourApiSpotClient(http, service_key=settings.tour_api_key)
            page1 = await client.list_by_area(l_dong_regn_cd="26", content_type_id="12",
                                              page=1, num_of_rows=100)
            full = await client.fetch_full(content_id="12345", content_type_id="12")
    """

    def __init__(self, http_client: httpx.AsyncClient, service_key: str) -> None:
        self._http = http_client
        self._service_key = service_key

    # ─── 목록 조회 ────────────────────────────────────────────
    async def list_by_area(
        self,
        *,
        l_dong_regn_cd: str,
        content_type_id: str,
        page: int,
        num_of_rows: int,
        l_dong_signgu_cd: str | None = None,
    ) -> dict[str, Any]:
        """areaBasedList2: 법정동 시도/시군구별 관광지 목록.

        매뉴얼 v4.4 기준:
        - KorService2는 `areaCode`를 받지 않음. `lDongRegnCd`로 통일.
        - 부산 시도 코드 = "26" (areaCode "6"과는 다른 체계).
        - lDongSignguCd는 lDongRegnCd가 있을 때만 의미 있음.
        """
        params = self._base_params() | {
            "lDongRegnCd": l_dong_regn_cd,                        # 부산 = '26'
            "contentTypeId": content_type_id,                     # '12'/'14'/'39'
            "pageNo": str(page),
            "numOfRows": str(num_of_rows),
            "arrange": "C",                                       # 수정일 역순
        }
        if l_dong_signgu_cd:
            params["lDongSignguCd"] = l_dong_signgu_cd
        return await self._get(LIST_ENDPOINT, params)

    # ─── 단일 스팟 상세 (4개 endpoint 병렬) ──────────────────
    async def fetch_full(
        self,
        *,
        content_id: str,
        content_type_id: str,
    ) -> dict[str, dict[str, Any]]:
        """detailCommon2 + detailIntro2 + detailInfo2 + detailImage2 병렬 호출.

        Returns:
            {
              "detailCommon2": <응답에서 추출한 item dict>,
              "detailIntro2":  <같은 형식>,
              "detailInfo2":   <같은 형식>,
              "detailImage2":  <원본 응답 그대로>  ← 다중 이미지라 list 처리 필요
            }
        """
        # asyncio.gather: 4개 호출을 동시에 던지고 모두 끝나면 모음
        results = await asyncio.gather(
            self._fetch_detail("detailCommon2", content_id, content_type_id),
            self._fetch_detail("detailIntro2", content_id, content_type_id),
            self._fetch_detail("detailInfo2", content_id, content_type_id),
            self._fetch_detail_image(content_id),
        )
        # zip으로 키-값 묶어 dict 만듦. strict=True는 길이 불일치 시 에러.
        return dict(zip(DETAIL_ENDPOINTS, results, strict=True))

    # ─── 내부: 단일 detail 호출 → 첫 item 추출 ────────────────
    async def _fetch_detail(
        self,
        endpoint: str,
        content_id: str,
        content_type_id: str,
    ) -> dict[str, Any]:
        """detailCommon2 / detailIntro2 / detailInfo2 호출 후 첫 item 추출.

        매뉴얼 v4.4 기준:
        - detailCommon2: contentId만 (contentTypeId 보내면 빈 응답 옴)
        - detailIntro2 / detailInfo2: contentId + contentTypeId 모두 필수
        """
        params = self._base_params() | _DETAIL_PAGE_PARAMS | {"contentId": content_id}
        if endpoint != "detailCommon2":
            params["contentTypeId"] = content_type_id
        payload = await self._get(f"/{endpoint}", params)
        return _extract_first_item(payload)

    async def _fetch_detail_image(self, content_id: str) -> dict[str, Any]:
        """detailImage2는 다중 이미지 → 응답 통째 반환 (parser가 list 처리).

        매뉴얼 v4.4 기준 detailImage2 파라미터:
        - 필수: serviceKey, MobileOS, MobileApp, contentId
        - 옵션: numOfRows, pageNo, _type, imageYN
        - subImageYN, contentTypeId는 KorService2 스펙에 없음 → 보내면 안 됨.
        """
        params = self._base_params() | _DETAIL_PAGE_PARAMS | {
            "contentId": content_id,
            "imageYN": "Y",
        }
        return await self._get("/detailImage2", params)

    # ─── 공통 ────────────────────────────────────────────────
    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """common/http.py의 재시도 래퍼 경유로 GET."""
        payload = await get_json(self._http, f"{TOURAPI_BASE_URL}{path}", params)
        _raise_on_tourapi_error(payload)
        return payload

    def _base_params(self) -> dict[str, str]:
        """모든 호출에 공통으로 붙는 파라미터."""
        return {
            "serviceKey": self._service_key,
            "MobileOS": "ETC",
            "MobileApp": "nolleo-onna",
            "_type": "json",
        }


def _extract_first_item(payload: dict[str, Any]) -> dict[str, Any]:
    """TourAPI 표준 응답에서 response.body.items.item의 첫 항목을 dict로 추출.

    응답이 비거나 예상 외 형태면 빈 dict 반환 (호출자가 결측치로 처리).
    """
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
    """TourAPI 비정상 응답을 즉시 예외로 올린다.

    성공 응답은 보통 response.header.resultCode="0000",
    파라미터 오류 등은 최상위 resultCode/resultMsg로 내려오기도 한다.
    """
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
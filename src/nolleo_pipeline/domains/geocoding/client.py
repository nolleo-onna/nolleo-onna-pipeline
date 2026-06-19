"""지오코딩 API 동기화 클라이언트."""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from nolleo_pipeline.common.http import _should_retry_http_status
from nolleo_pipeline.domains.geocoding.models import GeocodeResult
from nolleo_pipeline.domains.geocoding.parser import parse_kakao_address_response

KAKAO_ADDRESS_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class KakaoGeocodingClient:
    """Kakao Local API 주소 검색 클라이언트."""

    def __init__(self, http: httpx.AsyncClient, *, api_key: str) -> None:
        self._http = http
        self._api_key = api_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=(
            retry_if_exception_type((
                httpx.TransportError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ))
            | retry_if_exception(_should_retry_http_status)
        ),
        reraise=True,
    )
    async def geocode_address(self, address: str) -> GeocodeResult | None:
        """주소 문자열을 좌표로 변환."""
        response = await self._http.get(
            KAKAO_ADDRESS_SEARCH_URL,
            params={"query": address},
            headers={"Authorization": f"KakaoAK {self._api_key}"},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return parse_kakao_address_response(payload, query=address)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=(
            retry_if_exception_type((
                httpx.TransportError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ))
            | retry_if_exception(_should_retry_http_status)
        ),
        reraise=True,
    )
    async def search_keyword(self, query: str) -> dict[str, Any]:
        """키워드(업소명 등)로 장소를 검색."""
        response = await self._http.get(
            KAKAO_KEYWORD_SEARCH_URL,
            params={"query": query, "size": 15},
            headers={"Authorization": f"KakaoAK {self._api_key}"},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

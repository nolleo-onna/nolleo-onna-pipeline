"""TourAPI 관광지 집중률 클라이언트.

[이 파일이 왜 있냐]
- TatsCnctrRateService 호출을 한곳에 모음.
- 매뉴얼 §공공데이터포털 에러코드: _type=json이어도 에러 응답은 XML로 옴.
  → response.json() 직전 본문을 보고 JSON/XML 분기 후 명시적 예외로 변환.
  → spots에서 쓰는 common/http.get_json은 그대로 두고 (회귀 위험 X), 본 도메인만
     자체 retry + 분기 헬퍼 사용.
"""
from __future__ import annotations

from typing import Any, cast

import httpx
from defusedxml import ElementTree as DefusedElementTree
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

TOURAPI_CONGESTION_BASE_URL = (
    "https://apis.data.go.kr/B551011/TatsCnctrRateService"
)
LIST_ENDPOINT = "/tatsCnctrRatedList"


class TourApiClientError(Exception):
    """TourAPI 에러 응답(XML 또는 비정상 resultCode)을 변환한 예외.

    재시도 대상 아님 — 4xx/명세 에러는 즉시 위로 전파해서 호출자가 처리.
    """


class TourApiCongestionClient:
    """TatsCnctrRateService 호출 모음.

    사용 예:
        async with build_http_client() as http:
            client = TourApiCongestionClient(http, service_key=settings.tour_api_key)
            page1 = await client.list_by_signgu(
                area_cd="26", signgu_cd="26110", page=1, num_of_rows=100
            )
    """

    def __init__(self, http_client: httpx.AsyncClient, service_key: str) -> None:
        self._http = http_client
        self._service_key = service_key

    async def list_by_signgu(
        self,
        *,
        area_cd: str,
        signgu_cd: str,
        page: int,
        num_of_rows: int,
    ) -> dict[str, Any]:
        """tatsCnctrRateList: 시군구별 향후 30일치 집중률 예측.

        매뉴얼 v4.0:
        - baseYmd는 요청 파라미터 X (응답 필드). 한 번 호출에 향후 30일치가 옴.
        - areaCd, signguCd는 모두 필수.
        """
        params = self._base_params() | {
            "areaCd": area_cd,
            "signguCd": signgu_cd,
            "pageNo": str(page),
            "numOfRows": str(num_of_rows),
        }
        return await self._get(LIST_ENDPOINT, params)

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{TOURAPI_CONGESTION_BASE_URL}{path}"
        payload = await _request_json_or_raise_xml(self._http, url, params)
        _raise_on_result_code(payload)
        return payload

    def _base_params(self) -> dict[str, str]:
        return {
            "serviceKey": self._service_key,
            "MobileOS": "ETC",
            "MobileApp": "nolleo-onna",
            "_type": "json",
        }


# ─── 모듈 레벨: 재시도 + JSON/XML 분기 헬퍼 ───────────────────────

def _should_retry_http_status(exc: BaseException) -> bool:
    """429/5xx만 재시도 — 4xx는 우리가 잘못 보낸 것이라 재시도 무의미."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    return status == 429 or 500 <= status < 600


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
async def _request_json_or_raise_xml(
    client: httpx.AsyncClient, url: str, params: dict[str, str]
) -> dict[str, Any]:
    """GET → 본문이 XML이면 OpenAPI 에러로 raise, JSON이면 파싱해서 반환.

    매뉴얼 §공공데이터포털 에러코드:
        _type=json이라도 에러 응답은 <OpenAPI_ServiceResponse> XML로 옴.
        본문 첫 글자(`<` vs `{`)로 분기.

    재시도 대상은 TransportError/ReadTimeout/429/5xx만. TourApiClientError는
    4xx + XML 케이스에서도 그대로 위로 전파됨 (재시도 X).
    """
    response = await client.get(url, params=params)
    # retryable HTTP 상태는 본문 형식(XML/JSON)보다 우선 처리해
    # HTTPStatusError를 일으키고 tenacity 재시도 경로를 타게 한다.
    if response.status_code == 429 or response.status_code >= 500:
        response.raise_for_status()
    text = response.text.lstrip()

    if text.startswith("<"):
        # XML 본문 — 비즈니스/파라미터 오류(주로 200/4xx)를 명시적 예외로 변환
        raise _build_xml_error(text, status_code=response.status_code)

    # JSON 응답 — 4xx면 raise_for_status가 잡음 (5xx는 retry 대상에 걸림)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def _build_xml_error(text: str, *, status_code: int) -> TourApiClientError:
    """OpenAPI_ServiceResponse XML을 파싱해서 TourApiClientError 생성."""
    try:
        root = DefusedElementTree.fromstring(text)
    except DefusedElementTree.ParseError:
        return TourApiClientError(
            f"unparseable response (http={status_code}): {text[:200]}"
        )
    err_msg = root.findtext(".//errMsg") or "SERVICE ERROR"
    return_auth_msg = root.findtext(".//returnAuthMsg") or "UNKNOWN"
    return_reason_code = root.findtext(".//returnReasonCode") or "?"
    return TourApiClientError(
        f"TourAPI XML error: code={return_reason_code}, "
        f"reason={return_auth_msg}, msg={err_msg}, http_status={status_code}"
    )


def _raise_on_result_code(payload: dict[str, Any]) -> None:
    """JSON 응답의 resultCode가 '0000'이 아니면 TourApiClientError raise."""
    code: Any = None
    msg: Any = None
    response = payload.get("response")
    if isinstance(response, dict):
        header = response.get("header")
        if isinstance(header, dict):
            code = header.get("resultCode")
            msg = header.get("resultMsg")

    if code is None:
        # 일부 응답은 최상위 resultCode/resultMsg로 내려올 수 있어 fallback 처리.
        code = payload.get("resultCode")
        msg = payload.get("resultMsg")

    if code is None:
        return
    code_str = str(code)
    if code_str != "0000":
        raise TourApiClientError(
            f"TourAPI result code: {code_str}, msg={msg or 'unknown'}"
        )
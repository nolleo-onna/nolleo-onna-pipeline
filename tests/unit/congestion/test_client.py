"""TourApiCongestionClient 단위 테스트."""

from __future__ import annotations

import httpx
import pytest

from nolleo_pipeline.domains.congestion.client import (
    TourApiClientError,
    _raise_on_result_code,
    _request_json_or_raise_xml,
)


@pytest.mark.asyncio
async def test_retryable_http_status_is_raised_before_xml_parsing() -> None:
    """503 + XML 본문이어도 HTTPStatusError를 먼저 올린다 (재시도 경로 보장)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=503,
            headers={"Content-Type": "application/xml"},
            text=(
                "<OpenAPI_ServiceResponse><cmmMsgHeader>"
                "<returnReasonCode>99</returnReasonCode>"
                "<returnAuthMsg>SERVICE ERROR</returnAuthMsg>"
                "<errMsg>DOWN</errMsg>"
                "</cmmMsgHeader></OpenAPI_ServiceResponse>"
            ),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            # tenacity 데코레이터를 우회해 "핵심 분기"만 검증
            await _request_json_or_raise_xml.__wrapped__(
                client,
                "https://example.com",
                {},
            )


@pytest.mark.asyncio
async def test_xml_error_body_raises_tourapi_client_error() -> None:
    """200 + XML 에러 본문이면 TourApiClientError로 변환한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/xml"},
            text=(
                "<OpenAPI_ServiceResponse><cmmMsgHeader>"
                "<returnReasonCode>22</returnReasonCode>"
                "<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>"
                "<errMsg>SERVICE ERROR</errMsg>"
                "</cmmMsgHeader></OpenAPI_ServiceResponse>"
            ),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TourApiClientError, match="code=22"):
            await _request_json_or_raise_xml.__wrapped__(
                client,
                "https://example.com",
                {},
            )


def test_raise_on_result_code_fallback_top_level() -> None:
    """response.header 누락 시에도 최상위 resultCode를 검사한다."""
    payload = {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR"}
    with pytest.raises(TourApiClientError, match="30"):
        _raise_on_result_code(payload)

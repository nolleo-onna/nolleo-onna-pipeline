from __future__ import annotations

from nolleo_pipeline.domains.geocoding.parser import (
    address_looks_like_busan,
    build_keyword_search_queries,
    is_in_busan,
    parse_kakao_keyword_response,
)
from nolleo_pipeline.llm.place_address import parse_place_address_inference


def test_build_keyword_search_queries_prefers_region() -> None:
    queries = build_keyword_search_queries(name="온나식당", source_region="해운대구")
    assert queries == ["부산 해운대구 온나식당", "부산 온나식당"]


def test_parse_kakao_keyword_response_matches_place_name() -> None:
    result = parse_kakao_keyword_response(
        {
            "documents": [
                {
                    "place_name": "다른식당",
                    "x": "129.16",
                    "y": "35.16",
                    "road_address_name": "부산광역시 해운대구 해운대로 1",
                },
                {
                    "place_name": "온나식당",
                    "x": "129.1603",
                    "y": "35.1631",
                    "road_address_name": "부산광역시 해운대구 중동2로 10",
                },
            ]
        },
        query="부산 해운대구 온나식당",
        place_name="온나식당",
        place_tel=None,
    )

    assert result is not None
    assert result.method == "keyword"
    assert result.map_x == 129.1603
    assert "부산광역시" in (result.resolved_address or "")


def test_is_in_busan_rejects_out_of_range_coordinates() -> None:
    assert is_in_busan(129.16, 35.16) is True
    assert is_in_busan(126.98, 37.57) is False


def test_address_looks_like_busan() -> None:
    assert address_looks_like_busan("부산광역시 해운대구 해운대로 1") is True
    assert address_looks_like_busan("서울특별시 중구 세종대로 1") is False


def test_parse_place_address_inference_accepts_json_payload() -> None:
    result = parse_place_address_inference(
        '{"address":"부산광역시 해운대구 해운대로 1","confidence":0.82,"reason":"구군 일치"}',
        model_name="gpt-4o-mini",
    )

    assert result is not None
    assert result.address.startswith("부산")
    assert result.confidence == 0.82

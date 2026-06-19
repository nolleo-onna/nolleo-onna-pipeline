from __future__ import annotations

from nolleo_pipeline.domains.geocoding.parser import (
    normalize_address_for_geocode,
    parse_kakao_address_response,
)


def test_normalize_address_for_geocode_prepends_busan_when_missing() -> None:
    assert normalize_address_for_geocode("해운대구 해운대로 1") == "부산광역시 해운대구 해운대로 1"


def test_normalize_address_for_geocode_keeps_existing_busan_prefix() -> None:
    assert (
        normalize_address_for_geocode("부산광역시 해운대구 해운대로 1")
        == "부산광역시 해운대구 해운대로 1"
    )


def test_normalize_address_for_geocode_returns_none_for_blank() -> None:
    assert normalize_address_for_geocode("   ") is None
    assert normalize_address_for_geocode(None) is None


def test_normalize_address_for_geocode_splits_concatenated_road_and_lot() -> None:
    assert (
        normalize_address_for_geocode(
            "부산 기장군 정관읍 모전2길 1-7부산 기장군 정관읍 모전리 744-6, 1층"
        )
        == "부산광역시 기장군 정관읍 모전2길 1-7"
    )


def test_normalize_address_for_geocode_strips_postal_prefix() -> None:
    assert (
        normalize_address_for_geocode(
            "(46762) 부산광역시 강서구 명지오션시티10로 16, 상가241가호 (명지동, 영어도시 퀸덤1차)"
        )
        == "부산광역시 강서구 명지오션시티10로 16, 상가241가호 (명지동, 영어도시 퀸덤1차)"
    )


def test_parse_kakao_address_response_extracts_first_document() -> None:
    result = parse_kakao_address_response(
        {
            "documents": [
                {"x": "129.1603", "y": "35.1631"},
            ]
        },
        query="부산광역시 해운대구 해운대로 1",
    )

    assert result is not None
    assert result.map_x == 129.1603
    assert result.map_y == 35.1631
    assert result.normalized_query == "부산광역시 해운대구 해운대로 1"


def test_parse_kakao_address_response_returns_none_when_empty() -> None:
    assert parse_kakao_address_response({"documents": []}, query="없는주소") is None

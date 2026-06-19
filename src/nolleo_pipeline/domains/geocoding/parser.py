"""지오코딩 응답 파서."""
from __future__ import annotations

import re
from typing import Any

from nolleo_pipeline.domains.geocoding.models import GeocodeResult
from nolleo_pipeline.domains.good_price.matcher import (
    jaro_winkler_similarity,
    normalize_match_name,
    tel_match_score,
)

BUSAN_MAP_X_MIN = 128.85
BUSAN_MAP_X_MAX = 129.35
BUSAN_MAP_Y_MIN = 34.95
BUSAN_MAP_Y_MAX = 35.45
MIN_KEYWORD_NAME_SIMILARITY = 0.75


def _dedupe_concatenated_busan_address(address: str) -> str:
    """도로명+지번이 붙은 착한가격업소 주소에서 첫 유효 구간만 추출."""
    parts = [part.strip() for part in re.split(r"(?=부산)", address) if part.strip()]
    if len(parts) <= 1:
        return address

    for part in parts:
        if re.search(r"(로|길)\s*[\d-]", part):
            return part
    return parts[0]


def normalize_address_for_geocode(
    address: str | None,
    *,
    default_region: str = "부산광역시",
) -> str | None:
    """지오코딩 API에 넘길 주소 문자열을 정규화."""
    if address is None:
        return None

    normalized = " ".join(address.split())
    if not normalized:
        return None

    normalized = re.sub(r"^\(\d{5}\)\s*", "", normalized)
    normalized = _dedupe_concatenated_busan_address(normalized)
    normalized = re.sub(r",\s*\d+~\d+층\([^)]+\)\s*$", "", normalized)

    compact = normalized.replace(" ", "")
    if "부산" not in compact:
        return f"{default_region} {normalized}"
    if normalized.startswith("부산 ") and "광역시" not in compact:
        return normalized.replace("부산 ", "부산광역시 ", 1)
    return normalized


def parse_kakao_address_response(
    payload: dict[str, Any],
    *,
    query: str,
) -> GeocodeResult | None:
    """Kakao address search 응답에서 첫 좌표를 추출."""
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        return None

    first = documents[0]
    if not isinstance(first, dict):
        return None

    map_x = first.get("x")
    map_y = first.get("y")
    if map_x is None or map_y is None:
        return None

    return GeocodeResult(
        map_x=float(map_x),
        map_y=float(map_y),
        normalized_query=query,
        method="address",
    )


def is_in_busan(map_x: float, map_y: float) -> bool:
    """좌표가 부산권 내인지 확인."""
    return (
        BUSAN_MAP_X_MIN <= map_x <= BUSAN_MAP_X_MAX
        and BUSAN_MAP_Y_MIN <= map_y <= BUSAN_MAP_Y_MAX
    )


def build_keyword_search_queries(
    *,
    name: str,
    source_region: str | None,
) -> list[str]:
    """Kakao 키워드 검색용 쿼리 후보."""
    queries: list[str] = []
    if source_region:
        queries.append(f"부산 {source_region} {name}")
    queries.append(f"부산 {name}")
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        compact = query.strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
    return deduped


def _keyword_document_address(document: dict[str, Any]) -> str | None:
    road = document.get("road_address_name")
    if isinstance(road, str) and road.strip():
        return road.strip()
    address = document.get("address_name")
    if isinstance(address, str) and address.strip():
        return address.strip()
    return None


def _keyword_document_score(
    document: dict[str, Any],
    *,
    place_name: str,
    place_tel: str | None,
) -> float:
    candidate_name = document.get("place_name")
    if not isinstance(candidate_name, str):
        return 0.0
    name_score = jaro_winkler_similarity(
        normalize_match_name(place_name),
        normalize_match_name(candidate_name),
    )
    phone = document.get("phone")
    tel_score = 0.0
    if isinstance(phone, str):
        tel_score = tel_match_score(place_tel, phone)
    return max(name_score, tel_score)


def parse_kakao_keyword_response(
    payload: dict[str, Any],
    *,
    query: str,
    place_name: str,
    place_tel: str | None,
    min_name_similarity: float = MIN_KEYWORD_NAME_SIMILARITY,
) -> GeocodeResult | None:
    """Kakao keyword search 응답에서 업소명이 맞는 첫 좌표를 추출."""
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return None

    best: GeocodeResult | None = None
    best_score = -1.0
    for document in documents:
        if not isinstance(document, dict):
            continue
        score = _keyword_document_score(
            document,
            place_name=place_name,
            place_tel=place_tel,
        )
        if score < min_name_similarity:
            continue

        map_x = document.get("x")
        map_y = document.get("y")
        if map_x is None or map_y is None:
            continue

        map_x_f = float(map_x)
        map_y_f = float(map_y)
        if not is_in_busan(map_x_f, map_y_f):
            continue

        resolved_address = _keyword_document_address(document)
        if resolved_address and "부산" not in resolved_address.replace(" ", ""):
            continue

        candidate = GeocodeResult(
            map_x=map_x_f,
            map_y=map_y_f,
            normalized_query=query,
            resolved_address=resolved_address,
            method="keyword",
        )
        if score > best_score:
            best = candidate
            best_score = score

    return best


def address_looks_like_busan(address: str | None) -> bool:
    """주소 문자열이 부산으로 보이는지 확인."""
    if address is None:
        return False
    compact = address.replace(" ", "")
    return "부산" in compact

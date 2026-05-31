"""TourAPI 여행코스 응답 파서.

[이 파일이 왜 있냐]
- TourAPI 원본 JSON을 DB 친화적인 내부 레코드로 변환하는 순수 로직만 모은다.
- 외부 의존(http/db) 없이 변환만 담당해 단위 테스트를 쉽게 만든다.
- operation.md 정책(원본 보존 + 정규화 + 아이템 REPLACE)을 코드로 강제한다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nolleo_pipeline.common.hash_util import sha256_hex
from nolleo_pipeline.common.timezone import parse_tourapi_timestamp
from nolleo_pipeline.domains.travel_courses.models import (
    CourseItemRecord,
    CourseRawSnapshot,
    ParsedTravelCourse,
    TravelCourseRecord,
)

ENDPOINT_KEYS = ("detailCommon2", "detailIntro2", "detailInfo2", "detailImage2")


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_from_text(value: Any) -> int | None:
    text = _str(value)
    if text is None:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _km_from_text(value: Any) -> float | None:
    text = _str(value)
    if text is None:
        return None
    # "14.2Km", "약 3 km" 같은 케이스에서 숫자/점만 추출
    filtered = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not filtered:
        return None
    try:
        return float(Decimal(filtered))
    except (InvalidOperation, ValueError):
        return None


def _overview_hash(overview: str | None) -> str | None:
    if not overview:
        return None
    raw = overview.strip()
    if not raw:
        return None
    return sha256_hex(raw)


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items")
    if not isinstance(items, dict):
        # 이미 단일 item dict 형태로 전달된 경우 fallback
        if isinstance(payload, dict) and payload.get("subcontentid"):
            return [payload]
        return []
    item = items.get("item")
    if isinstance(item, list):
        return [i for i in item if isinstance(i, dict)]
    if isinstance(item, dict):
        return [item]
    # 간헐적으로 parser에 단일 item dict만 들어와도 파싱 가능하게 방어
    if payload.get("subcontentid"):
        return [payload]
    return []


def _subnum_sort_key(item: dict[str, Any]) -> tuple[int, int]:
    """detailInfo2.subnum 기준 정렬 키.

    - subnum이 있으면 그 순서를 우선 사용
    - subnum이 없거나 비정상이면 뒤로 보내고 입력 순서를 유지한다
    """
    text = _str(item.get("subnum"))
    if text is None:
        return (1, 0)
    try:
        return (0, int(text))
    except ValueError:
        return (1, 0)


def build_raw_snapshot(
    content_id: str,
    endpoints: dict[str, dict[str, Any]],
    *,
    fetched_at: datetime,
) -> CourseRawSnapshot:
    raw_json = {
        "endpoints": {
            key: {
                "data": endpoints.get(key) or {},
                "fetched_at": fetched_at.isoformat(),
            }
            for key in ENDPOINT_KEYS
        }
    }
    return CourseRawSnapshot(
        content_id=content_id,
        raw_json=raw_json,
        fetched_at=fetched_at,
    )


def parse_course(
    endpoints: dict[str, dict[str, Any]],
    *,
    synced_at: datetime,
    fetched_at: datetime,
) -> ParsedTravelCourse:
    """detail 응답 묶음을 ParsedTravelCourse로 정규화."""
    common = endpoints.get("detailCommon2") or {}
    if not common.get("contentid"):
        raise ValueError("detailCommon2.contentid가 비었다 — 정규화 불가")

    content_id = str(common["contentid"])
    overview = _str(common.get("overview"))

    course = TravelCourseRecord(
        content_id=content_id,
        title=str(common.get("title") or "").strip() or f"course-{content_id}",
        overview=overview,
        overview_hash=_overview_hash(overview),
        theme=_str(common.get("theme")),
        taketime=_str(common.get("taketime")),
        taketime_minutes=_int_from_text(common.get("taketime")),
        distance=_str(common.get("distance")),
        distance_km=_km_from_text(common.get("distance")),
        schedule=_str(common.get("schedule")),
        infocenter_tourcourse=_str(common.get("infocentertourcourse")),
        first_image=_str(common.get("firstimage")),
        first_image_cpyrht_div_cd=_str(common.get("cpyrhtDivCd")),
        l_dong_regn_cd=_str(common.get("lDongRegnCd")),
        source_modified_time=parse_tourapi_timestamp(_str(common.get("modifiedtime"))),
        source_created_at=parse_tourapi_timestamp(_str(common.get("createdtime"))),
        synced_at=synced_at,
        is_active=True,
    )

    info_payload = endpoints.get("detailInfo2") or {}
    info_items = _extract_items(info_payload)

    # 코스 추천에서 순서(1->2->3)가 핵심이므로 subnum 기준 정렬 후 serial_num을 다시 부여한다.
    indexed_items = list(enumerate(info_items))
    indexed_items.sort(key=lambda pair: (_subnum_sort_key(pair[1]), pair[0]))
    ordered_items = [raw for _, raw in indexed_items]

    records: list[CourseItemRecord] = []
    for idx, raw in enumerate(ordered_items, start=1):
        sub_content_id = _str(raw.get("subcontentid"))
        records.append(
            CourseItemRecord(
                course_content_id=content_id,
                serial_num=idx,  # subnum 기준으로 정렬한 순서(1..N)
                sub_content_id=sub_content_id,
                matched_spot_id=sub_content_id,  # 동일 ID 매칭 우선, 실패시 repo에서 NULL 처리 가능
                sub_name=_str(raw.get("subname")),
                sub_overview=_str(raw.get("subdetailoverview")),
                sub_image=_str(raw.get("subdetailimg")),
                sub_image_alt=_str(raw.get("subdetailalt")),
            )
        )

    return ParsedTravelCourse(
        course=course,
        items=records,
        raw=build_raw_snapshot(content_id, endpoints, fetched_at=fetched_at),
    )
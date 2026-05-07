"""TourAPI 관광지 집중률 응답 파서.

[입력] tatsCnctrRateList 응답 dict
[출력] CongestionForecastRecord 리스트 (한 번 호출에 시군구별 30일치)

매칭(content_id 채움)은 여기서 안 함 — repository 책임.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from nolleo_pipeline.domains.congestion.models import (
    CongestionForecastRecord,
    CongestionSource,
    derive_level,
)


def parse_congestion_response(
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    source: CongestionSource = "tourapi",
) -> list[CongestionForecastRecord]:
    """TourAPI 응답 → 레코드 리스트. 응답이 비면 빈 list."""
    body = payload.get("response", {}).get("body", {})
    items_field = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items_field, dict):
        return []
    item = items_field.get("item")
    raw_items: list[dict[str, Any]] = []
    if isinstance(item, list):
        raw_items = [i for i in item if isinstance(i, dict)]
    elif isinstance(item, dict):
        raw_items = [item]

    return [
        _parse_one(raw, fetched_at=fetched_at, source=source)
        for raw in raw_items
    ]


def _parse_one(
    raw: dict[str, Any],
    *,
    fetched_at: datetime,
    source: CongestionSource,
) -> CongestionForecastRecord:
    rate = float(raw["cnctrRate"])
    return CongestionForecastRecord(
        content_id=None,                                          # 매칭 단계에서 채움
        area_cd=str(raw["areaCd"]),
        signgu_cd=str(raw["signguCd"]),
        raw_tats_name=str(raw["tAtsNm"]).strip(),
        area_name=_str(raw.get("areaNm")),
        signgu_name=_str(raw.get("signguNm")),
        base_ymd=_parse_ymd(str(raw["baseYmd"])),
        concentration_rate=rate,
        level=derive_level(rate),
        source=source,
        fetched_at=fetched_at,
    )


def _str(value: Any) -> str | None:
    """빈 문자열/None을 일관되게 None으로."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_ymd(text: str) -> date:
    """'YYYYMMDD' → date. KST 기준 날짜."""
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
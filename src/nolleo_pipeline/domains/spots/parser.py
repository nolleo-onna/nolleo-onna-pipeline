"""TourAPI 관광지 응답 파서.

[이 파일이 왜 있냐]
- TourAPI JSON은 카멜케이스 키 + 다 문자열 + 누락 컬럼 흔함
- DB는 깔끔한 타입을 원함
- 그 사이를 잇는 변환 로직만 모아둔 파일. 외부 의존(http, db) 0 → 단위 테스트 쉬움.

[입력] 4개 endpoint 응답 dict 묶음
[출력] ParsedSpot (4종 레코드: core / detail / images / raw)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from nolleo_pipeline.common.hash_util import sha256_hex
from nolleo_pipeline.common.timezone import parse_tourapi_timestamp
from nolleo_pipeline.domains.spots.models import (
    ParsedSpot,
    SpotCoreRecord,
    SpotDetailsRecord,
    SpotImageRecord,
    SpotRawSnapshot,
)

# 4개 endpoint 키. raw_json 표준 구조에 들어가는 순서/이름.
ENDPOINT_KEYS = ("detailCommon2", "detailIntro2", "detailInfo2", "detailImage2")

# ─── 헬퍼: 빈 값 정규화 ────────────────────────────────────────
# TourAPI는 값이 비면 빈 문자열("")을 자주 주는데, DB엔 NULL이 깔끔.

def _str(value: Any) -> str | None:
    """빈 문자열/None을 일관되게 None으로 정규화."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None  # 빈 문자열이면 None


def _float(value: Any) -> float | None:
    """문자열 → float 변환. 변환 실패하면 None."""
    text = _str(value)
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _bool_yn(value: Any) -> bool | None:
    """'Y'/'N' 형태를 bool로. 그 외는 None."""
    text = _str(value)
    if text is None:
        return None
    upper = text.upper()
    if upper == "Y":
        return True
    if upper == "N":
        return False
    return None


# ─── 핵심: overview_hash ─────────────────────────────────────

def compute_overview_hash(overview: str | None) -> str | None:
    """overview의 SHA-256 hex (64자). 빈 값이면 None.

    이전 sync 결과의 hash와 비교해서 같으면 LLM 재호출 skip.
    operation.md §3 SPOT_DETAILS 변경 감지 정책의 핵심.
    """
    if not overview or not overview.strip():
        return None
    return sha256_hex(overview.strip())


# ─── 핵심: raw 스냅샷 표준 구조 만들기 ────────────────────────

def build_raw_snapshot(
    content_id: str,
    endpoints: dict[str, dict[str, Any]],
    fetched_at: datetime,
) -> SpotRawSnapshot:
    """4개 endpoint 응답을 SPOTS_RAW_SNAPSHOTS의 raw_json 표준 구조로 묶는다."""
    raw_json = {
        "endpoints": {
            key: {
                "data": endpoints.get(key) or {},
                "fetched_at": fetched_at.isoformat(),
            }
            for key in ENDPOINT_KEYS
        }
    }
    return SpotRawSnapshot(
        content_id=content_id,
        raw_json=raw_json,
        fetched_at=fetched_at,
    )


# ─── 각 테이블별 파서 ─────────────────────────────────────────

def parse_core(common: dict[str, Any], synced_at: datetime) -> SpotCoreRecord:
    """detailCommon2 응답 → SPOTS_CORE 레코드."""
    return SpotCoreRecord(
        content_id=str(common["contentid"]),                    # 필수. 없으면 KeyError → 호출자 처리
        content_type_id=str(common["contenttypeid"]),
        title=str(common["title"]).strip(),
        map_x=_float(common.get("mapx")),                        # 경도
        map_y=_float(common.get("mapy")),                        # 위도
        l_dong_regn_cd=_str(common.get("lDongRegnCd")),
        l_dong_signgu_cd=_str(common.get("lDongSignguCd")),
        lcls_systm_1=_str(common.get("lclsSystm1")),
        lcls_systm_2=_str(common.get("lclsSystm2")),
        lcls_systm_3=_str(common.get("lclsSystm3")),
        first_image=_str(common.get("firstimage")),
        first_image2=_str(common.get("firstimage2")),
        source_modified_time=parse_tourapi_timestamp(common.get("modifiedtime")),
        synced_at=synced_at,
        is_active=True,
    )


def parse_detail(
    common: dict[str, Any],
    intro: dict[str, Any] | None,
) -> SpotDetailsRecord:
    """detailCommon2 + detailIntro2 → SPOT_DETAILS 레코드.

    parking 정보는 contenttypeid에 따라 키가 다름 (parkinglodging/parkingfood/...).
    여러 키를 시도해서 처음 만나는 값을 사용.
    """
    overview = _str(common.get("overview"))

    # parking_* 키들이 contenttype마다 다르므로 차례로 시도
    parking_raw = None
    if intro:
        for key in (
            "parking",
            "parkinglodging",
            "parkingfood",
            "parkingculture",
            "parkingleports",
            "parkingshopping",
        ):
            if intro.get(key):
                parking_raw = intro[key]
                break

    return SpotDetailsRecord(
        content_id=str(common["contentid"]),
        tel=_str(common.get("tel")),
        homepage=_str(common.get("homepage")),
        addr1=_str(common.get("addr1")),
        addr2=_str(common.get("addr2")),
        zipcode=_str(common.get("zipcode")),
        overview=overview,
        overview_hash=compute_overview_hash(overview),           # 핵심
        intro=intro or None,                                      # JSONB 원본 통째 보관
        parking_available=_bool_yn(parking_raw),
        created_time=parse_tourapi_timestamp(common.get("createdtime")),
    )


def parse_images(
    content_id: str,
    common: dict[str, Any],
    image_payload: dict[str, Any] | None,
) -> list[SpotImageRecord]:
    """detailImage2 → SPOT_IMAGES 레코드 N장.

    detailImage2가 비어있으면 detailCommon2의 firstimage를 1장짜리로 fallback.
    serial_num 중복 방지는 여기서 처리.
    """
    items: list[dict[str, Any]] = []

    if image_payload:
        # detailImage2 응답 구조: response.body.items.item이 list 또는 dict
        body = image_payload.get("response", {}).get("body", {}) \
            if "response" in image_payload else image_payload
        items_raw = body.get("items", {}) if isinstance(body, dict) else {}
        items_field = items_raw.get("item") if isinstance(items_raw, dict) else None
        if isinstance(items_field, list):
            items = [i for i in items_field if isinstance(i, dict)]
        elif isinstance(items_field, dict):
            items = [items_field]

    records: list[SpotImageRecord] = []
    seen_serial: set[str] = set()
    for raw in items:
        origin = _str(raw.get("originimgurl"))
        if not origin:
            continue                                              # URL 없는 행은 skip
        serial = _str(raw.get("serialnum")) or str(len(records) + 1)
        if serial in seen_serial:
            continue                                              # 같은 sync 안에서 중복 방어
        seen_serial.add(serial)
        records.append(
            SpotImageRecord(
                content_id=content_id,
                origin_img_url=origin,
                small_img_url=_str(raw.get("smallimageurl")),
                img_name=_str(raw.get("imgname")),
                serial_num=serial,
            )
        )

    # detailImage2가 통째로 비었으면 firstimage를 1장짜리로 사용
    if not records:
        first = _str(common.get("firstimage"))
        if first:
            records.append(
                SpotImageRecord(
                    content_id=content_id,
                    origin_img_url=first,
                    small_img_url=_str(common.get("firstimage2")),
                    img_name=None,
                    serial_num="1",
                )
            )
    return records


# ─── 메인 진입점: 4개 응답 → ParsedSpot ───────────────────────

def parse_spot(
    endpoints: dict[str, dict[str, Any]],
    *,
    synced_at: datetime,
    fetched_at: datetime,
) -> ParsedSpot:
    """4개 endpoint 응답 묶음을 단일 ParsedSpot으로 정규화.

    Args:
        endpoints: {"detailCommon2": {...}, "detailIntro2": {...}, ...}
        synced_at: SPOTS_CORE.synced_at에 들어갈 timezone-aware datetime
        fetched_at: RAW snapshot에 박을 timezone-aware datetime

    Raises:
        ValueError: detailCommon2.contentid가 없으면 정규화 불가.
    """
    common = endpoints.get("detailCommon2") or {}
    if not common.get("contentid"):
        raise ValueError("detailCommon2.contentid가 비었다 — 정규화 불가")

    content_id = str(common["contentid"])
    intro = endpoints.get("detailIntro2")
    image = endpoints.get("detailImage2")

    return ParsedSpot(
        core=parse_core(common, synced_at=synced_at),
        detail=parse_detail(common, intro),
        images=parse_images(content_id, common, image),
        raw=build_raw_snapshot(content_id, endpoints, fetched_at=fetched_at),
    )
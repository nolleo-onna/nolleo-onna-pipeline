"""착한가격업소/음식 가격 원천 응답 파서."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from nolleo_pipeline.domains.good_price.models import (
    FoodPlaceMenuRecord,
    FoodPlaceRecord,
    FoodPlaceSource,
    FoodPlaceSourceRecord,
    MenuSource,
    ObservationSourceType,
    ParsedFoodPlace,
)

_MENU_NAME_PATTERNS = (
    ("품목", "가격"),
    ("메뉴", "가격"),
    ("item", "price"),
    ("menu", "price"),
)


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """공공데이터 응답에서 item list를 유연하게 추출."""
    candidates: list[Any] = [
        payload.get("items"),
        payload.get("item"),
        payload.get("data"),
        payload.get("body", {}).get("items") if isinstance(payload.get("body"), dict) else None,
    ]

    response = payload.get("response")
    if isinstance(response, dict):
        body = response.get("body")
        if isinstance(body, dict):
            candidates.extend([
                body.get("items"),
                body.get("item"),
                body.get("data"),
            ])
            items = body.get("items")
            if isinstance(items, dict):
                candidates.append(items.get("item"))

    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
        if isinstance(candidate, dict):
            item = candidate.get("item")
            if isinstance(item, list):
                return [row for row in item if isinstance(row, dict)]
            if isinstance(item, dict):
                return [item]
            if candidate:
                return [candidate]
    return []


def parse_good_price_shop_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
) -> ParsedFoodPlace:
    """이전 이름 호환용: 착한가격업소 목록 API row를 정규화."""
    return parse_good_price_store_row(row, fetched_at=fetched_at)


def parse_good_price_store_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
) -> ParsedFoodPlace:
    """부산 착한가격업소 목록 API row를 fd_food_* 공통 모델로 정규화."""
    return _parse_row(
        row,
        fetched_at=fetched_at,
        place_source="good_price_store",
        menu_source="admin_manual",
        source_type="api",
    )


def parse_good_price_menu_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
) -> ParsedFoodPlace:
    """부산 착한가격업소 메뉴 API row를 fd_food_* 공통 모델로 정규화."""
    return _parse_row(
        row,
        fetched_at=fetched_at,
        place_source="good_price_menu",
        menu_source="good_price_menu",
        source_type="api",
        external_id=_good_price_menu_external_id(row),
    )


def parse_good_price_file_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
    source_file: str | None = None,
) -> ParsedFoodPlace:
    """착한가격업소 CSV/파일 row를 fd_food_* 공통 모델로 정규화."""
    raw = dict(row)
    if source_file:
        raw["_source_file"] = source_file
    return _parse_row(
        raw,
        fetched_at=fetched_at,
        place_source="good_price_file",
        menu_source="good_price_file",
        source_type="file_import",
    )


def parse_busan_food_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
) -> ParsedFoodPlace:
    """부산맛집정보 API row를 fd_food_* 공통 모델로 정규화."""
    return _parse_row(
        row,
        fetched_at=fetched_at,
        place_source="busan_food",
        menu_source="admin_manual",
        source_type="api",
    )


def _parse_row(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
    place_source: FoodPlaceSource,
    menu_source: MenuSource,
    source_type: ObservationSourceType,
    external_id: str | None = None,
) -> ParsedFoodPlace:
    name = _first(
        row,
        "업소명",
        "업소",
        "상호",
        "상호명",
        "bsshNm",
        "sj",
        "SJ",
        "MAIN_TITLE",
        "PLACE",
        "name",
        "shopName",
        "bsnsNm",
    )
    if name is None:
        raise ValueError("food place name is required")

    address = _first(
        row,
        "주소",
        "주소(도로명 새주소)",
        "도로명주소",
        "소재지주소",
        "사업장 주소",
        "adres",
        "ADDR",
        "ADDR1",
        "addr",
        "address",
    )
    addr2 = _first(row, "ADDR2", "주소 기타", "상세주소")
    if address is not None and addr2 is not None:
        address = f"{address} {addr2}"
    tel = _normalize_tel(
        _first(row, "연락처", "전화번호", "tel", "TEL", "CNTCT_TEL", "phone", "전화")
    )
    category = _first(row, "업종", "업소구분", "cn", "category", "business_category")
    source_region = _first(
        row,
        "시군",
        "구군",
        "구군명",
        "GUGUN_NM",
        "지역",
        "locale",
        "source_region",
        "signguNm",
    )
    representative_menu = _first(row, "대표메뉴", "주메뉴", "대표품목", "RPRSNTV_MENU", "mainMenu")
    description = _first(row, "소개", "상세내용", "설명", "intrcn", "ITEMCNTNTS", "description")
    external_id = external_id or _first(
        row, "idx", "IDX", "UC_SEQ", "id", "ID", "external_id", "shopId"
    )
    if external_id is None:
        external_id = _fallback_external_id(row, name=name, address=address, tel=tel)

    menus = _extract_menus(
        row,
        fetched_at=fetched_at,
        source=menu_source,
        source_type=source_type,
    )
    if representative_menu is None and menus:
        representative_menu = menus[0].menu_name

    place = FoodPlaceRecord(
        name=name,
        business_category=category,
        normalized_category=_normalize_category(category),
        is_course_food_candidate=_is_food_category(category),
        address=address,
        tel=tel,
        business_hours_raw=_first(
            row,
            "영업시간",
            "운영시간",
            "운영 및 시간",
            "USAGE_DAY_WEEK_AND_TIME",
            "bsnTime",
            "business_hours",
        ),
        description=description,
        representative_menu=representative_menu,
        delivery_available=_bool_yn(
            _first(row, "배달", "배달가능", "배달가능여부", "delivery_available")
        ),
        parking_available=_bool_yn(
            _first(row, "주차", "주차가능", "주차가능여부", "parkngAt", "parking")
        ),
        source_region=source_region,
        map_x=_float(_first(row, "경도", "LNG", "mapx", "map_x", "lon", "lng", "longitude")),
        map_y=_float(_first(row, "위도", "LAT", "mapy", "map_y", "lat", "latitude")),
        is_active=True,
    )
    source = FoodPlaceSourceRecord(
        source=place_source,
        external_id=external_id,
        source_region=source_region,
        raw_json=row,
        fetched_at=fetched_at,
    )
    return ParsedFoodPlace(place=place, source=source, menus=menus)


def _extract_menus(
    row: dict[str, Any],
    *,
    fetched_at: datetime,
    source: MenuSource,
    source_type: ObservationSourceType,
) -> list[FoodPlaceMenuRecord]:
    menus: list[FoodPlaceMenuRecord] = []
    seen: set[str] = set()

    for index in range(1, 21):
        name = _first_menu_value(row, index=index, value_names=("품목", "메뉴", "item", "menu"))
        price_raw = _first_menu_value(row, index=index, value_names=("가격", "price"))
        if name is None and price_raw is None:
            continue
        if name is None:
            continue
        price = _parse_price(price_raw)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        menus.append(
            FoodPlaceMenuRecord(
                menu_name=name,
                price=price,
                display_order=index,
                source=source,
                source_type=source_type,
                is_representative=(len(menus) == 0),
                observed_at=fetched_at,
                raw_payload=row,
                review_status="approved",
            )
        )

    single_menu_name = _first(row, "itemNm", "ITEM_NM", "메뉴명", "품목명")
    if single_menu_name is not None and single_menu_name.casefold() not in seen:
        seen.add(single_menu_name.casefold())
        menus.append(
            FoodPlaceMenuRecord(
                menu_name=single_menu_name,
                price=_parse_price(_first(row, "menuPrc", "MENU_PRC", "메뉴가격", "가격")),
                display_order=len(menus) + 1,
                source=source,
                source_type=source_type,
                is_representative=(len(menus) == 0),
                observed_at=fetched_at,
                raw_payload=row,
                review_status="approved",
            )
        )

    for name_key, price_key in _discover_menu_pairs(row):
        name = _str(row.get(name_key))
        if name is None:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        menus.append(
            FoodPlaceMenuRecord(
                menu_name=name,
                price=_parse_price(row.get(price_key)),
                display_order=len(menus) + 1,
                source=source,
                source_type=source_type,
                is_representative=(len(menus) == 0),
                observed_at=fetched_at,
                raw_payload=row,
                review_status="approved",
            )
        )
    return menus


def _discover_menu_pairs(row: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    keys = list(row)
    for name_prefix, price_prefix in _MENU_NAME_PATTERNS:
        for key in keys:
            match = re.fullmatch(rf"{re.escape(name_prefix)}\s*([0-9]+)", key, re.IGNORECASE)
            if not match:
                continue
            suffix = match.group(1)
            for price_key in keys:
                if re.fullmatch(rf"{re.escape(price_prefix)}\s*{suffix}", price_key, re.IGNORECASE):
                    pairs.append((key, price_key))
                    break
    return pairs


def _first_menu_value(
    row: dict[str, Any],
    *,
    index: int,
    value_names: tuple[str, ...],
) -> str | None:
    keys: list[str] = []
    for name in value_names:
        keys.extend([
            f"{name}{index}",
            f"{name}_{index}",
            f"{name}{index:02d}",
            f"{name}_{index:02d}",
        ])
    return _first(row, *keys)


def _first(row: dict[str, Any], *keys: str) -> str | None:
    lower_map = {str(key).strip().casefold(): key for key in row}
    for key in keys:
        actual = lower_map.get(key.casefold())
        if actual is None:
            continue
        value = _str(row.get(actual))
        if value is not None:
            return value
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    text = _str(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_price(value: Any) -> int | None:
    text = _str(value)
    if text is None:
        return None
    normalized = text.replace(" ", "")
    first_number = re.search(r"\d[\d,]*", normalized)
    if first_number is None:
        return None
    token = first_number.group(0)
    if "," in token and not re.fullmatch(r"\d{1,3}(,\d{3})+", token):
        return None
    return int(token.replace(",", ""))


def _normalize_tel(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", "", value)


def _bool_yn(value: str | None) -> bool | None:
    if value is None:
        return None
    upper = value.strip().upper()
    if upper in {"Y", "YES", "1", "TRUE", "가능", "있음", "유", "O"}:
        return True
    if upper in {"N", "NO", "0", "FALSE", "불가능", "없음", "무", "X"}:
        return False
    return None


def _normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    text = category.replace(" ", "")
    if any(token in text for token in ("한식", "분식", "김밥", "백반", "국밥")):
        return "food_korean"
    if "중식" in text or "중국" in text:
        return "food_chinese"
    if "일식" in text or "초밥" in text:
        return "food_japanese"
    if "양식" in text or "경양식" in text:
        return "food_western"
    if "카페" in text or "커피" in text:
        return "food_cafe"
    if "미용" in text:
        return "beauty"
    if "목욕" in text or "세탁" in text:
        return "bath"
    if "숙박" in text:
        return "lodging"
    if _is_food_category(category):
        return "food_other"
    return "other"


def _is_food_category(category: str | None) -> bool:
    if category is None:
        return True
    text = category.replace(" ", "")
    non_food = ("미용", "목욕", "세탁", "숙박", "이미용")
    if any(token in text for token in non_food):
        return False
    food_tokens = ("요식", "음식", "한식", "중식", "일식", "양식", "분식", "식당", "카페")
    return any(token in text for token in food_tokens)


def _fallback_external_id(
    row: dict[str, Any],
    *,
    name: str,
    address: str | None,
    tel: str | None,
) -> str:
    source = "|".join([name, address or "", tel or "", str(sorted(row.items()))])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def _good_price_menu_external_id(row: dict[str, Any]) -> str | None:
    name = _first(row, "bsshNm", "업소명", "sj", "SJ")
    if name is None:
        return None
    return f"bsshNm:{name.casefold()}"

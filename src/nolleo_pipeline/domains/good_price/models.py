"""Good Price 도메인 정규화 모델."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

FoodPlaceSource = Literal[
    "good_price_shop",
    "good_price_store",
    "good_price_menu",
    "good_price_file",
    "redtable",
    "busan_food",
    "model_restaurant",
    "admin_manual",
]

MenuSource = Literal[
    "good_price_menu",
    "good_price_file",
    "redtable",
    "admin_manual",
    "user_report",
    "crawler",
]

ObservationSourceType = Literal["api", "file_import", "admin_manual", "user_report", "crawler"]


class FoodPlaceRecord(BaseModel):
    """food_places UPSERT용 장소 레코드."""

    model_config = ConfigDict(extra="forbid")

    name: str
    business_category: str | None = None
    normalized_category: str | None = None
    is_course_food_candidate: bool = False
    address: str | None = None
    tel: str | None = None
    business_hours_raw: str | None = None
    description: str | None = None
    representative_menu: str | None = None
    delivery_available: bool | None = None
    parking_available: bool | None = None
    source_region: str | None = None
    map_x: float | None = None
    map_y: float | None = None
    is_active: bool = True


class FoodPlaceSourceRecord(BaseModel):
    """food_place_sources UPSERT용 원천 식별자/원본 row."""

    model_config = ConfigDict(extra="forbid")

    source: FoodPlaceSource
    external_id: str
    source_region: str | None = None
    raw_json: dict[str, Any]
    fetched_at: datetime


class FoodPlaceMenuRecord(BaseModel):
    """food_place_menus / food_price_observations 공통 메뉴 가격 레코드."""

    model_config = ConfigDict(extra="forbid")

    menu_name: str
    price: int | None = None
    currency: str = "KRW"
    display_order: int | None = None
    source: MenuSource
    source_type: ObservationSourceType
    is_representative: bool = False
    observed_at: datetime
    raw_payload: dict[str, Any] | None = None
    review_status: str = "approved"


class ParsedFoodPlace(BaseModel):
    """단일 음식/가격 장소의 정규화 결과."""

    model_config = ConfigDict(extra="forbid")

    place: FoodPlaceRecord
    source: FoodPlaceSourceRecord
    menus: list[FoodPlaceMenuRecord]

"""Geocoding 도메인 모델."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class GeocodeResult(BaseModel):
    """주소/키워드 지오코딩 결과."""

    model_config = ConfigDict(extra="forbid")

    map_x: float = Field(description="경도")
    map_y: float = Field(description="위도")
    normalized_query: str
    provider: str = "kakao"
    resolved_address: str | None = None
    method: str = "address"


@dataclass(frozen=True)
class FoodPlaceGeocodeTarget:
    """좌표 보강 대상 음식 장소."""

    food_place_id: int
    name: str
    address: str


@dataclass(frozen=True)
class FoodPlaceGeocodeRunResult:
    """음식 장소 지오코딩 실행 결과."""

    places_scanned: int
    geocoded_count: int
    failed_count: int
    skipped_no_address: int
    dry_run: bool


@dataclass(frozen=True)
class FoodPlaceInferenceTarget:
    """주소·좌표가 비어 있는 음식 장소."""

    food_place_id: int
    name: str
    tel: str | None
    source_region: str | None
    representative_menu: str | None
    menu_names: tuple[str, ...]


@dataclass(frozen=True)
class FoodPlaceInferenceRunResult:
    """Kakao/LLM 주소·좌표 추론 실행 결과."""

    places_scanned: int
    resolved_count: int
    keyword_resolved_count: int
    llm_resolved_count: int
    failed_count: int
    skipped_low_confidence: int
    dry_run: bool

"""프로젝트 공통 상수."""

from __future__ import annotations

from typing import Final

BUSAN_REGN_CD: Final[int] = 26

CONTENT_TYPE_IDS: Final[tuple[int, ...]] = (12, 14, 15, 25, 39)

CONTROLLED_TAG_VOCAB: Final[dict[str, list[str]]] = {
    "mood": ["활기찬", "조용한", "감성적인", "로컬한", "자연친화"],
    "weather_fit": ["맑음", "비", "더위", "추위", "실내중심"],
    "budget_tier": ["저예산", "중간", "프리미엄"],
    "travel_with": ["혼자", "친구", "연인", "가족"],
}

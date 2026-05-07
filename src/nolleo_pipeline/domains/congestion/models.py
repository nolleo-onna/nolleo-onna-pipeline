"""Congestion 도메인 정규화 레코드 모델 (Pydantic).

[이 파일이 왜 있냐]
- TourAPI 응답 → DB 적재 사이의 다리.
- level은 cnctrRate에서 자체 파생 (operation.md §3 SPOT_CONGESTION_FORECAST).
- content_id는 매칭 단계 책임이라 모델 필드는 nullable.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CongestionSource = Literal["tourapi", "llm", "rule"]


def derive_level(concentration_rate: float) -> int:
    """cnctrRate → level 5단계 자체 파생.

    operation.md §3 SPOT_CONGESTION_FORECAST의 반열림 구간:
        < 20      → 1 (한산)
        [20, 40)  → 2
        [40, 60)  → 3 (보통)
        [60, 80)  → 4
        ≥ 80      → 5 (혼잡)

    경계값(20.0/40.0/60.0/80.0)은 항상 상위 등급에 속함.
    """
    if concentration_rate < 20:
        return 1
    if concentration_rate < 40:
        return 2
    if concentration_rate < 60:
        return 3
    if concentration_rate < 80:
        return 4
    return 5


class CongestionForecastRecord(BaseModel):
    """SPOT_CONGESTION_FORECAST UPSERT용 레코드.

    매칭 책임 분리:
        - 파서가 만든 직후엔 content_id=None
        - repository.match_by_raw_name 호출 후 채워질 수 있음
        - 매칭 실패 row는 unmatched partial UK
          (area_cd, signgu_cd, raw_tats_name, base_ymd, source)로 적재
    """

    model_config = ConfigDict(extra="forbid")

    content_id: str | None = None
    area_cd: str
    signgu_cd: str
    raw_tats_name: str
    area_name: str | None = None
    signgu_name: str | None = None
    base_ymd: date
    concentration_rate: float
    level: int                                   # 파서가 derive_level()로 박음
    source: CongestionSource = "tourapi"
    fetched_at: datetime
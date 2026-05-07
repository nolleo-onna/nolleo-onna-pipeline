"""Congestion 모델 단위 테스트 — level 반열림 구간 파생 정확성 검증.

operation.md §3 SPOT_CONGESTION_FORECAST의 level 5단계 정책:
    < 20      → 1 (한산)
    [20, 40)  → 2
    [40, 60)  → 3 (보통)
    [60, 80)  → 4
    ≥ 80      → 5 (혼잡)

경계값(20.0/40.0/60.0/80.0)은 항상 상위 등급에 속해야 함 — 운영 데이터에
정확히 20.0 같은 값이 들어왔을 때 어디로 분류되는지 명세 보장.
"""
from __future__ import annotations

import pytest

from nolleo_pipeline.domains.congestion.models import derive_level


@pytest.mark.parametrize(
    ("rate", "expected_level"),
    [
        # < 20 → 1 (한산)
        (0.0, 1),
        (19.99, 1),
        # [20, 40) → 2  (경계 20.0이 정확히 등급 2)
        (20.0, 2),
        (39.99, 2),
        # [40, 60) → 3 (경계 40.0이 정확히 등급 3)
        (40.0, 3),
        (59.99, 3),
        # [60, 80) → 4 (경계 60.0이 정확히 등급 4)
        (60.0, 4),
        (79.99, 4),
        # ≥ 80 → 5 (경계 80.0이 정확히 등급 5)
        (80.0, 5),
        (100.0, 5),
    ],
)
def test_derive_level_half_open_intervals(rate: float, expected_level: int) -> None:
    """반열림 구간 — 모든 경계값이 상위 등급에 속한다."""
    assert derive_level(rate) == expected_level

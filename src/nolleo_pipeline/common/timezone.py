"""KST/UTC 시간 유틸리티."""

from datetime import datetime


def now_kst() -> datetime:
    """KST 현재 시각을 반환한다."""
    raise NotImplementedError


def to_utc(value: datetime) -> datetime:
    """입력 시각을 UTC로 변환한다."""
    raise NotImplementedError


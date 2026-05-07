"""KST/UTC 시간 유틸리티.

[이 파일이 왜 있냐]
operation.md §11 규칙: 모든 시각 컬럼은 TIMESTAMPTZ. 즉 datetime을 만들 때
"timezone 정보가 붙어 있어야" 한다. naive datetime(시간대 정보 없음)이 들어가면
DB가 UTC로 잘못 해석할 수도 있고 KST 기준 비교가 깨진다.
이 파일은 "tz가 붙은 datetime만 만든다"는 규약을 강제하는 helper.
"""

from __future__ import annotations  # 타입 힌트를 문자열로 평가 (순환참조 회피용 표준 옵션)

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo  # 파이썬 3.9+ 표준 타임존 라이브러리

# 상수 두 개. tzinfo는 datetime에 붙이는 "타임존 객체" 타입.
KST: tzinfo = ZoneInfo("Asia/Seoul")
UTC: tzinfo = UTC

def now_utc() -> datetime:
    """ timezone UTC 현재 시각을 반환한다.
    
    """
    return datetime.now(UTC)

def now_kst() -> datetime:
    """ timezone KST 현재 시각을 반환한다.
    
    base_ymd 같은 "오늘 날짜 (KST 기준)" 계산할 때 사용.
    예: now_kst().date() → 한국 시간 기준 오늘 날짜.
    """
    return datetime.now(KST)

def to_utc(value: datetime) -> datetime:
    """ 입력 datetime을 UTC로 변환한다.
    
    실수로 naive datetime이 들어오면 즉시 에러로 막는다 (§11 정책).
    timezone-aware라면 안전하게 UTC로 변환만 해서 리턴.
    """
    if value.tzinfo is None:
        raise ValueError(
            "timezone-naive datetime은 허용되지 않는다 (operation.md §11). "
            "now_utc() / now_kst()를 쓰거나 tz를 명시해서 만들 것."
        )
    return value.astimezone(UTC)

def parse_tourapi_timestamp(value: str | None) -> datetime | None:
    """TourAPI의 'YYYYMMDDHHMMSS' 14자리 문자열을 KST datetime으로 파싱.

    TourAPI 응답의 createdtime/modifiedtime은 14자리 문자열 형태:
        "20260315090000"  → 2026-03-15 09:00:00 (한국 시간)

    빈 값 / 이상한 길이 → None 반환 (조용히 skip).
    """
    if not value:
        return None
    cleaned = value.strip()
    # 정확히 14자리 숫자가 아니면 무효로 판정
    if len(cleaned) != 14 or not cleaned.isdigit():
        return None
    # 슬라이싱으로 연/월/일/시/분/초를 잘라낸다
    return datetime(
        year=int(cleaned[0:4]),
        month=int(cleaned[4:6]),
        day=int(cleaned[6:8]),
        hour=int(cleaned[8:10]),
        minute=int(cleaned[10:12]),
        second=int(cleaned[12:14]),
        tzinfo=KST,  #  KST로
    )
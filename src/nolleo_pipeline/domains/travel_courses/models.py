"""Travel Courses 도메인 정규화 레코드 모델 (Pydantic).

[이 파일이 왜 있냐]
- TourAPI 코스 응답은 문자열/누락 값이 많아 그대로 DB에 넣기 어렵다.
- DB 적재 전에 "정규화된 내부 타입"을 강제해 파싱/저장 경계를 명확히 한다.
- Pydantic 검증으로 필수값/타입 오류를 DB 직전에 조기 차단한다.

"""

from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

class TravelCourseRecord(BaseModel):
    """TRAVEL_COURSES UPSERT용 레코드."""
    # `extra=forbid` = 정의되지 않은 필드가 들어오면 예외. 오타 방어
    model_config = ConfigDict(extra="forbid")

    content_id: str                      # 코스의 고유 ID (문자열)
    title: str                           # 코스 제목 (예: "서울 야경 데이트 코스")
    overview: str | None = None          # 코스에 대한 전반적인 설명
    overview_hash: str | None = None     # 설명(overview) 글이 변경되었는지 빠르게 비교하기 위한 해시값
    theme: str | None = None             # 코스 테마 (예: "가족여행", "힐링")
    taketime: str | None = None          # 소요 시간 (문자열 형태, 예: "3시간 30분")
    taketime_minutes: int | None = None  # 소요 시간을 계산하기 좋게 분(minute) 단위 숫자로 변환한 값 (예: 210)
    distance: str | None = None          # 이동 거리 (문자열 형태, 예: "4.5km")
    distance_km: float | None = None     # 이동 거리를 계산하기 좋게 실수(float) 형태로 변환한 값 (예: 4.5)
    schedule: str | None = None          # 당일, 1박2일 등의 일정 정보
    infocenter_tourcourse: str | None = None # 문의처/안내소 정보
    first_image: str | None = None       # 코스 대표 이미지 URL
    l_dong_regn_cd: str | None = None    # 법정동 지역 코드 (행정구역 분류용)
    source_modified_time: datetime | None = None # 원본 데이터(공공데이터 등)가 수정된 시간
    created_time: datetime | None = None  # 이 레코드가 처음 생성된 시간
    synced_at: datetime                  # 데이터가 최종 동기화(업데이트)된 시간 (필수값)
    is_active: bool = True               # 이 코스가 현재 유효한지 여부 (기본값 True)

# 코스에 포함된 상세 장소들
# 예: 카페 ➔ 낙산공원 ➔ 식당
class CourseItemRecord(BaseModel):
    """COURSE_ITEMS UPSERT용 레코드."""
    model_config = ConfigDict(extra="forbid")
    
    course_content_id: str         # 부모가 되는 'TravelCourseRecord'의 content_id (어느 코스에 속해있는지 연결)
    serial_num: int                # 코스 내에서의 순서 (1번 장소, 2번 장소...)
    sub_content_id: str | None = None # 세부 장소의 고유 ID
    matched_spot_id: str | None = None # 자체 서비스 내의 실제 장소(Spot) DB와 매칭된 ID
    sub_name: str | None = None    # 세부 장소 이름 (예: "낙산공원 낙조")
    sub_overview: str | None = None# 세부 장소에 대한 설명
    sub_image: str | None = None   # 세부 장소 이미지 URL
    sub_image_alt: str | None = None # 이미지 태그용 대체 텍스트 (웹 접근성용 설명)

class CourseRawSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_id: str
    raw_json: dict[str, Any]
    fetched_at: datetime

class ParsedTravelCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course: TravelCourseRecord
    items: list[CourseItemRecord]
    raw: CourseRawSnapshot
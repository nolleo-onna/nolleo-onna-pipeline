"""Spots 도메인 정규화 레코드 모델 (Pydantic).

[이 파일이 왜 있냐]
- TourAPI JSON은 키가 카멜케이스, 값이 다 문자열, 어떤 키는 누락 등 "지저분"
- DB는 정해진 컬럼/타입으로 받아야 함
- 그 사이 다리: "정규화된 데이터 형태" 클래스를 명확히 정의
- Pydantic이 타입/필수값 자동 검증 → 잘못된 데이터를 DB 직전에 한 번 더 거름
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# Literal은 "이 값들 중 하나만 허용" 타입 힌트. DB CHECK 제약과 일치시킨다.
TagSource = Literal["llm", "rule", "manual"]

class SpotCoreRecord(BaseModel):
    """SPOTS UPSERT용 레코드.

    필수 필드(content_id, content_type_id, title, synced_at)만 NOT NULL,
    나머지는 None 허용 (TourAPI 응답에 누락된 경우 흔함).
    """
    #`extra=forbid` = 정의되지 않은 필드가 들어오면 예외. 오타 방어
    model_config = ConfigDict(extra="forbid")

    content_id:str
    content_type_id:str
    title:str
    source_tour_api: bool = True
    source_busan_food: bool = False

    map_x: float | None = None      # 경도
    map_y: float | None = None      # 위도

    l_dong_regn_cd: str | None = None
    l_dong_signgu_cd: str | None = None
    lcls_systm_1: str | None = None
    lcls_systm_2: str | None = None
    lcls_systm_3: str | None = None

    first_image: str | None = None
    first_image2: str | None = None
    first_image_cpyrht_div_cd: str | None = None

    source_modified_time: datetime | None = None
    synced_at: datetime              # 호출자가 now_utc() 박아 넣음

    is_active: bool = True

class SpotDetailsRecord(BaseModel):
    """SPOT_DETAILS UPSERT용 레코드.

    overview_hash가 변경 감지의 핵심.
    이전 값과 같으면 LLM 재호출 skip.
    """
    model_config = ConfigDict(extra="forbid")

    content_id: str
    tel: str | None = None
    tel_name: str | None = None
    homepage: str | None = None
    addr1: str | None = None
    addr2: str | None = None
    zipcode: str | None = None

    overview: str | None = None
    overview_hash: str | None = None  # SHA-256 hex 64자
    intro: dict[str, Any] | None = None  # JSONB 그대로

    parking_available: bool | None = None
    source_created_at: datetime | None = None

class SpotImageRecord(BaseModel):
    """SPOT_IMAGES REPLACE용 레코드.

    한 번의 sync에서 (content_id, serial_num) 중복 방지는 호출자 책임.
    """
    model_config = ConfigDict(extra="forbid")

    content_id: str
    origin_img_url: str
    small_img_url: str | None = None
    img_name: str | None = None
    cpyrht_div_cd: str | None = None
    serial_num: str

class SpotRawSnapshot(BaseModel):
    """SPOTS_RAW_SNAPSHOTS UPSERT용. 원본 JSON 통째 보관.

    raw_json 표준 구조 (operation.md §3):
        {
          "endpoints": {
            "detailCommon2": {"data": {...}, "fetched_at": "..."},
            "detailIntro2":  {...},
            "detailInfo2":   {...},
            "detailImage2":  {...}
          }
        }
    """
    model_config = ConfigDict(extra="forbid")

    content_id: str
    raw_json: dict[str, Any]
    fetched_at: datetime


class ParsedSpot(BaseModel):
    """파서 출력 — 단일 스팟의 4종 레코드 묶음.

    repository.py가 이걸 받아서 "한 트랜잭션 안에" 4테이블에 분배.
    """
    model_config = ConfigDict(extra="forbid")

    core: SpotCoreRecord
    detail: SpotDetailsRecord
    images: list[SpotImageRecord]
    raw: SpotRawSnapshot

    # @property = "메서드인데 ()없이 속성처럼 호출". 편의용.
    @property
    def content_id(self) -> str:
        return self.core.content_id

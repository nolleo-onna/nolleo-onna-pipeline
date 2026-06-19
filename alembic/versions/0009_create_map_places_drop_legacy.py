"""create mp_map_places and drop legacy unprefixed course tables

[배경]
- 인수인계 없이 새 개발자가 Flyway로 진행한 변경(통합 지도 테이블 mp_map_places 생성)을
  Alembic으로 흡수해 마이그레이션 단일화.
- 0005에서 접두사 없이 만들었던 generated_courses / generated_course_items /
  course_decisions 는 cs_* 로 재생성되며 남은 0행 잔존 테이블이므로 제거.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 통합 지도 장소 테이블 (sp_spots / fd_food_places 를 지도 노출용으로 통합).
    op.execute("""
    CREATE TABLE public.mp_map_places (
        id              BIGSERIAL    PRIMARY KEY,
        place_type      VARCHAR(10)  NOT NULL,
        original_id     VARCHAR(50)  NOT NULL,
        name            VARCHAR(200) NOT NULL,
        district        VARCHAR(50),
        category        VARCHAR(10)  NOT NULL,
        longitude       NUMERIC(10,7),
        latitude        NUMERIC(10,7),
        image_url       TEXT,
        min_price       INTEGER,
        is_free         BOOLEAN      NOT NULL DEFAULT FALSE,
        is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_mp_map_places_type_original UNIQUE (place_type, original_id)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.mp_map_places IS '지도 노출용 통합 장소(스팟/음식점)';
    COMMENT ON COLUMN public.mp_map_places.id IS '내부 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.mp_map_places.place_type IS '원천 장소 타입(spot/food 등)';
    COMMENT ON COLUMN public.mp_map_places.original_id IS '원천 테이블 식별자';
    COMMENT ON COLUMN public.mp_map_places.name IS '장소명';
    COMMENT ON COLUMN public.mp_map_places.district IS '시군구';
    COMMENT ON COLUMN public.mp_map_places.category IS '표준 카테고리 코드';
    COMMENT ON COLUMN public.mp_map_places.longitude IS '경도';
    COMMENT ON COLUMN public.mp_map_places.latitude IS '위도';
    COMMENT ON COLUMN public.mp_map_places.image_url IS '대표 이미지 URL';
    COMMENT ON COLUMN public.mp_map_places.min_price IS '최저 가격(음식점)';
    COMMENT ON COLUMN public.mp_map_places.is_free IS '무료 여부';
    COMMENT ON COLUMN public.mp_map_places.is_active IS '서비스 노출 활성 여부';
    COMMENT ON COLUMN public.mp_map_places.created_at IS '생성 시각';
    COMMENT ON COLUMN public.mp_map_places.updated_at IS '수정 시각';
    """)

    op.execute("CREATE INDEX idx_mp_map_places_category ON public.mp_map_places (category);")
    op.execute("CREATE INDEX idx_mp_map_places_district ON public.mp_map_places (district);")
    op.execute("CREATE INDEX idx_mp_map_places_min_price ON public.mp_map_places (min_price);")

    # 0005가 접두사 없이 만들었던 잔존 테이블 정리(cs_* 로 대체됨, FK 의존성 없음).
    op.execute("DROP TABLE IF EXISTS public.course_decisions;")
    op.execute("DROP TABLE IF EXISTS public.generated_course_items;")
    op.execute("DROP TABLE IF EXISTS public.generated_courses;")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_mp_map_places_min_price;")
    op.execute("DROP INDEX IF EXISTS public.idx_mp_map_places_district;")
    op.execute("DROP INDEX IF EXISTS public.idx_mp_map_places_category;")
    op.execute("DROP TABLE IF EXISTS public.mp_map_places;")
    # 잔존 레거시 테이블 재생성은 하지 않는다(데이터 0행, cs_* 로 대체됨).

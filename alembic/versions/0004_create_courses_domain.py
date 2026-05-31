"""create travel courses tables for MVP

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.travel_courses (
        content_id              VARCHAR(20) PRIMARY KEY,
        title                   VARCHAR(200) NOT NULL,
        overview                TEXT,
        overview_hash           VARCHAR(64),
        theme                   VARCHAR(100),
        taketime                VARCHAR(50),
        taketime_minutes        INTEGER
            CHECK (taketime_minutes IS NULL OR taketime_minutes >= 0),
        distance                VARCHAR(50),
        distance_km             NUMERIC(7,3)
            CHECK (distance_km IS NULL OR distance_km >= 0),
        schedule                TEXT,
        infocenter_tourcourse   VARCHAR(200),
        first_image             TEXT,
        first_image_cpyrht_div_cd VARCHAR(10),
        l_dong_regn_cd          VARCHAR(2),
        source_modified_time    TIMESTAMPTZ,
        source_created_at       TIMESTAMPTZ,
        synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        is_active               BOOLEAN NOT NULL DEFAULT TRUE,
        inactive_since          TIMESTAMPTZ
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.travel_courses IS 'TourAPI 여행코스 마스터';
    COMMENT ON COLUMN public.travel_courses.content_id IS '여행코스 콘텐츠 ID(PK)';
    COMMENT ON COLUMN public.travel_courses.title IS '코스명';
    COMMENT ON COLUMN public.travel_courses.overview IS '코스 소개 원문';
    COMMENT ON COLUMN public.travel_courses.overview_hash IS '코스 소개 변경 감지 해시';
    COMMENT ON COLUMN public.travel_courses.theme IS '코스 테마';
    COMMENT ON COLUMN public.travel_courses.taketime IS '원천 소요시간 문자열';
    COMMENT ON COLUMN public.travel_courses.taketime_minutes IS '파싱된 소요시간(분)';
    COMMENT ON COLUMN public.travel_courses.distance IS '원천 거리 문자열';
    COMMENT ON COLUMN public.travel_courses.distance_km IS '파싱된 거리(km)';
    COMMENT ON COLUMN public.travel_courses.schedule IS '코스 일정 원문';
    COMMENT ON COLUMN public.travel_courses.infocenter_tourcourse IS '문의처';
    COMMENT ON COLUMN public.travel_courses.first_image IS '대표 이미지 URL';
    COMMENT ON COLUMN public.travel_courses.first_image_cpyrht_div_cd IS '대표 이미지 저작권 구분 코드';
    COMMENT ON COLUMN public.travel_courses.l_dong_regn_cd IS '시도 코드';
    COMMENT ON COLUMN public.travel_courses.source_modified_time IS '원천 API 수정 시각';
    COMMENT ON COLUMN public.travel_courses.source_created_at IS '원천 API 생성 시각';
    COMMENT ON COLUMN public.travel_courses.synced_at IS '파이프라인 동기화 시각';
    COMMENT ON COLUMN public.travel_courses.updated_at IS '행 수정 시각';
    COMMENT ON COLUMN public.travel_courses.is_active IS '서비스 노출 활성 여부';
    COMMENT ON COLUMN public.travel_courses.inactive_since IS '비활성 전환 시각';
    """)

    op.execute("""
    CREATE TABLE public.travel_course_raw_snapshots (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES public.travel_courses(content_id) ON DELETE CASCADE,
        raw_json        JSONB       NOT NULL,
        fetched_at      TIMESTAMPTZ NOT NULL,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.travel_course_raw_snapshots IS '여행코스 원천 응답 스냅샷(JSONB)';
    COMMENT ON COLUMN public.travel_course_raw_snapshots.content_id IS '여행코스 ID(PK, travel_courses FK)';
    COMMENT ON COLUMN public.travel_course_raw_snapshots.raw_json IS '엔드포인트별 원천 응답 JSON';
    COMMENT ON COLUMN public.travel_course_raw_snapshots.fetched_at IS '원천 응답 수집 시각';
    COMMENT ON COLUMN public.travel_course_raw_snapshots.updated_at IS '행 수정 시각';
    """)

    op.execute("""
    CREATE TABLE public.course_items (
        id                  BIGSERIAL   PRIMARY KEY,
        course_content_id   VARCHAR(20) NOT NULL
            REFERENCES public.travel_courses(content_id) ON DELETE CASCADE,
        serial_num          INTEGER     NOT NULL CHECK (serial_num >= 1),
        sub_content_id      VARCHAR(20),
        matched_spot_id     VARCHAR(20)
            REFERENCES public.spots(content_id) ON DELETE SET NULL,
        sub_name            VARCHAR(200),
        sub_overview        TEXT,
        sub_image           TEXT,
        sub_image_alt       VARCHAR(200),
        CONSTRAINT uk_course_items_course_serial UNIQUE (course_content_id, serial_num)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.course_items IS '여행코스 하위 방문지 목록';
    COMMENT ON COLUMN public.course_items.id IS '내부 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.course_items.course_content_id IS '상위 여행코스 ID(FK)';
    COMMENT ON COLUMN public.course_items.serial_num IS '코스 내 방문 순서(1부터)';
    COMMENT ON COLUMN public.course_items.sub_content_id IS '원천 하위 콘텐츠 ID';
    COMMENT ON COLUMN public.course_items.matched_spot_id IS '매칭된 스팟 ID(FK)';
    COMMENT ON COLUMN public.course_items.sub_name IS '원천 하위 장소명';
    COMMENT ON COLUMN public.course_items.sub_overview IS '원천 하위 장소 설명';
    COMMENT ON COLUMN public.course_items.sub_image IS '원천 하위 장소 이미지 URL';
    COMMENT ON COLUMN public.course_items.sub_image_alt IS '원천 하위 장소 이미지 설명';
    """)

    op.execute("""
    CREATE INDEX idx_course_items_matched_spot
        ON public.course_items (matched_spot_id);
    """)

    op.execute("""
    CREATE TRIGGER trg_travel_courses_updated_at
        BEFORE UPDATE ON public.travel_courses
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)

    op.execute("""
    CREATE TRIGGER trg_travel_course_raw_snapshots_updated_at
        BEFORE UPDATE ON public.travel_course_raw_snapshots
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_travel_course_raw_snapshots_updated_at ON public.travel_course_raw_snapshots;")
    op.execute("DROP TRIGGER IF EXISTS trg_travel_courses_updated_at ON public.travel_courses;")
    op.execute("DROP INDEX IF EXISTS public.idx_course_items_matched_spot;")
    op.execute("DROP TABLE IF EXISTS public.course_items;")
    op.execute("DROP TABLE IF EXISTS public.travel_course_raw_snapshots;")
    op.execute("DROP TABLE IF EXISTS public.travel_courses;")

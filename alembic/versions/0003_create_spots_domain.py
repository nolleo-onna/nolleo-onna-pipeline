"""create spots domain tables for MVP

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.sp_spots (
        content_id                  VARCHAR(20)  PRIMARY KEY,
        content_type_id             VARCHAR(8)   NOT NULL
            CHECK (content_type_id IN ('12', '14', '28', '39')),
        title                       VARCHAR(200) NOT NULL,
        source_tour_api             BOOLEAN      NOT NULL DEFAULT TRUE,
        source_busan_food           BOOLEAN      NOT NULL DEFAULT FALSE,
        map_x                       NUMERIC(10,7),
        map_y                       NUMERIC(10,7),
        geog                        geography(POINT, 4326) GENERATED ALWAYS AS (
            CASE
                WHEN map_x IS NOT NULL AND map_y IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint(map_x, map_y), 4326)::geography
                ELSE NULL
            END
        ) STORED,
        l_dong_regn_cd              VARCHAR(2),
        l_dong_signgu_cd            VARCHAR(5),
        lcls_systm_1                VARCHAR(10),
        lcls_systm_2                VARCHAR(10),
        lcls_systm_3                VARCHAR(10),
        first_image                 TEXT,
        first_image2                TEXT,
        first_image_cpyrht_div_cd   VARCHAR(10),
        source_modified_time        TIMESTAMPTZ,
        synced_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        is_active                   BOOLEAN      NOT NULL DEFAULT TRUE,
        inactive_since              TIMESTAMPTZ,
        CONSTRAINT chk_sp_spots_map_x
            CHECK (map_x IS NULL OR map_x BETWEEN -180 AND 180),
        CONSTRAINT chk_sp_spots_map_y
            CHECK (map_y IS NULL OR map_y BETWEEN -90 AND 90)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.sp_spots IS '관광 스팟 핵심 테이블(핫패스)';
    COMMENT ON COLUMN public.sp_spots.content_id IS 'TourAPI 콘텐츠 ID(PK)';
    COMMENT ON COLUMN public.sp_spots.content_type_id IS '콘텐츠 타입(12/14/28/39)';
    COMMENT ON COLUMN public.sp_spots.title IS '스팟명';
    COMMENT ON COLUMN public.sp_spots.source_tour_api IS 'TourAPI 수집 여부';
    COMMENT ON COLUMN public.sp_spots.source_busan_food IS '착한가격/부산미식 등 보조 소스 여부';
    COMMENT ON COLUMN public.sp_spots.map_x IS '경도';
    COMMENT ON COLUMN public.sp_spots.map_y IS '위도';
    COMMENT ON COLUMN public.sp_spots.geog IS 'PostGIS geography 포인트(생성 컬럼)';
    COMMENT ON COLUMN public.sp_spots.l_dong_regn_cd IS '법정동 시도 코드';
    COMMENT ON COLUMN public.sp_spots.l_dong_signgu_cd IS '법정동 시군구 코드';
    COMMENT ON COLUMN public.sp_spots.lcls_systm_1 IS '분류코드 대분류';
    COMMENT ON COLUMN public.sp_spots.lcls_systm_2 IS '분류코드 중분류';
    COMMENT ON COLUMN public.sp_spots.lcls_systm_3 IS '분류코드 소분류';
    COMMENT ON COLUMN public.sp_spots.first_image IS '대표 이미지 URL';
    COMMENT ON COLUMN public.sp_spots.first_image2 IS '보조 대표 이미지 URL';
    COMMENT ON COLUMN public.sp_spots.first_image_cpyrht_div_cd IS '대표 이미지 저작권 유형';
    COMMENT ON COLUMN public.sp_spots.source_modified_time IS '원천 API 수정 시각';
    COMMENT ON COLUMN public.sp_spots.synced_at IS '파이프라인 동기화 시각';
    COMMENT ON COLUMN public.sp_spots.updated_at IS '행 수정 시각';
    COMMENT ON COLUMN public.sp_spots.is_active IS '서비스 노출 활성 여부';
    COMMENT ON COLUMN public.sp_spots.inactive_since IS '비활성 전환 시각';
    """)

    op.execute("""
    CREATE TABLE public.sp_spot_details (
        content_id                  VARCHAR(20) PRIMARY KEY
            REFERENCES public.sp_spots(content_id) ON DELETE CASCADE,
        tel                         VARCHAR(50),
        tel_name                    VARCHAR(100),
        homepage                    TEXT,
        addr1                       TEXT,
        addr2                       TEXT,
        zipcode                     VARCHAR(10),
        overview                    TEXT,
        overview_hash               VARCHAR(64),
        intro                       JSONB,
        parking_available           BOOLEAN,
        source_created_at           TIMESTAMPTZ,
        updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.sp_spot_details IS '스팟 상세 테이블(콜드 데이터)';
    COMMENT ON COLUMN public.sp_spot_details.content_id IS '스팟 ID(PK, sp_spots FK)';
    COMMENT ON COLUMN public.sp_spot_details.tel IS '연락처';
    COMMENT ON COLUMN public.sp_spot_details.tel_name IS '연락처명';
    COMMENT ON COLUMN public.sp_spot_details.homepage IS '홈페이지 URL';
    COMMENT ON COLUMN public.sp_spot_details.addr1 IS '기본 주소';
    COMMENT ON COLUMN public.sp_spot_details.addr2 IS '상세 주소';
    COMMENT ON COLUMN public.sp_spot_details.zipcode IS '우편번호';
    COMMENT ON COLUMN public.sp_spot_details.overview IS '소개 원문';
    COMMENT ON COLUMN public.sp_spot_details.overview_hash IS '소개 텍스트 변경 감지 해시';
    COMMENT ON COLUMN public.sp_spot_details.intro IS 'TourAPI intro 원문(JSONB)';
    COMMENT ON COLUMN public.sp_spot_details.parking_available IS '주차 가능 여부';
    COMMENT ON COLUMN public.sp_spot_details.source_created_at IS '원천 API 생성 시각';
    COMMENT ON COLUMN public.sp_spot_details.updated_at IS '행 수정 시각';
    """)

    op.execute("""
    CREATE TABLE public.sp_spots_raw_snapshots (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES public.sp_spots(content_id) ON DELETE CASCADE,
        raw_json        JSONB       NOT NULL,
        fetched_at      TIMESTAMPTZ NOT NULL,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.sp_spots_raw_snapshots IS '스팟 원천 응답 스냅샷(JSONB)';
    COMMENT ON COLUMN public.sp_spots_raw_snapshots.content_id IS '스팟 ID(PK, sp_spots FK)';
    COMMENT ON COLUMN public.sp_spots_raw_snapshots.raw_json IS '엔드포인트별 원천 응답 JSON';
    COMMENT ON COLUMN public.sp_spots_raw_snapshots.fetched_at IS '원천 응답 수집 시각';
    COMMENT ON COLUMN public.sp_spots_raw_snapshots.updated_at IS '행 수정 시각';
    """)

    op.execute("""
    CREATE TABLE public.sp_spot_images (
        id              BIGSERIAL    PRIMARY KEY,
        content_id      VARCHAR(20)  NOT NULL
            REFERENCES public.sp_spots(content_id) ON DELETE CASCADE,
        origin_img_url  TEXT         NOT NULL,
        small_img_url   TEXT,
        img_name        VARCHAR(200),
        cpyrht_div_cd   VARCHAR(10),
        serial_num      VARCHAR(20)  NOT NULL,
        CONSTRAINT uk_sp_spot_images_content_serial UNIQUE (content_id, serial_num)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.sp_spot_images IS '스팟 이미지 목록(1:N)';
    COMMENT ON COLUMN public.sp_spot_images.id IS '내부 이미지 식별자';
    COMMENT ON COLUMN public.sp_spot_images.content_id IS '스팟 ID(FK)';
    COMMENT ON COLUMN public.sp_spot_images.origin_img_url IS '원본 이미지 URL';
    COMMENT ON COLUMN public.sp_spot_images.small_img_url IS '썸네일 이미지 URL';
    COMMENT ON COLUMN public.sp_spot_images.img_name IS '이미지 설명';
    COMMENT ON COLUMN public.sp_spot_images.cpyrht_div_cd IS '이미지 저작권 유형';
    COMMENT ON COLUMN public.sp_spot_images.serial_num IS '이미지 순번';
    """)

    op.execute("""
    CREATE INDEX idx_sp_spots_geog
        ON public.sp_spots USING gist (geog)
        WHERE is_active = TRUE;
    """)
    op.execute("""
    CREATE INDEX idx_sp_spots_signgu_active
        ON public.sp_spots (l_dong_signgu_cd)
        WHERE is_active = TRUE;
    """)

    op.execute("""
    CREATE TRIGGER trg_sp_spots_updated_at
        BEFORE UPDATE ON public.sp_spots
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)

    op.execute("""
    CREATE TRIGGER trg_sp_spot_details_updated_at
        BEFORE UPDATE ON public.sp_spot_details
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)

    op.execute("""
    CREATE TRIGGER trg_sp_spots_raw_snapshots_updated_at
        BEFORE UPDATE ON public.sp_spots_raw_snapshots
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sp_spots_raw_snapshots_updated_at "
        "ON public.sp_spots_raw_snapshots;"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_sp_spot_details_updated_at ON public.sp_spot_details;")
    op.execute("DROP TRIGGER IF EXISTS trg_sp_spots_updated_at ON public.sp_spots;")
    op.execute("DROP INDEX IF EXISTS public.idx_sp_spots_signgu_active;")
    op.execute("DROP INDEX IF EXISTS public.idx_sp_spots_geog;")
    op.execute("DROP TABLE IF EXISTS public.sp_spot_images;")
    op.execute("DROP TABLE IF EXISTS public.sp_spots_raw_snapshots;")
    op.execute("DROP TABLE IF EXISTS public.sp_spot_details;")
    op.execute("DROP TABLE IF EXISTS public.sp_spots;")

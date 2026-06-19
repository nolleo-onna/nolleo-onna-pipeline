"""create food price domain tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.fd_food_places (
        id                          BIGSERIAL    PRIMARY KEY,
        name                        VARCHAR(200) NOT NULL,
        business_category           VARCHAR(100),
        normalized_category         VARCHAR(50)
            CHECK (
                normalized_category IS NULL OR normalized_category IN (
                    'food_korean',
                    'food_chinese',
                    'food_japanese',
                    'food_western',
                    'food_noodle',
                    'food_meat',
                    'food_cafe',
                    'food_other',
                    'beauty',
                    'bath',
                    'lodging',
                    'other'
                )
            ),
        is_course_food_candidate    BOOLEAN      NOT NULL DEFAULT FALSE,
        address                     TEXT,
        tel                         VARCHAR(100),
        business_hours_raw          VARCHAR(500),
        description                 TEXT,
        representative_menu         VARCHAR(200),
        delivery_available          BOOLEAN,
        parking_available           BOOLEAN,
        source_region               VARCHAR(50),
        map_x                       NUMERIC(10,7),
        map_y                       NUMERIC(10,7),
        geog                        geography(POINT, 4326) GENERATED ALWAYS AS (
            CASE
                WHEN map_x IS NOT NULL AND map_y IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint(map_x, map_y), 4326)::geography
                ELSE NULL
            END
        ) STORED,
        is_active                   BOOLEAN      NOT NULL DEFAULT TRUE,
        inactive_since              TIMESTAMPTZ,
        created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        created_by                  VARCHAR(50),
        updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_by                  VARCHAR(50),
        CONSTRAINT chk_fd_food_places_map_x
            CHECK (map_x IS NULL OR map_x BETWEEN -180 AND 180),
        CONSTRAINT chk_fd_food_places_map_y
            CHECK (map_y IS NULL OR map_y BETWEEN -90 AND 90)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.fd_food_places IS '부산 음식/가격 후보 장소 마스터';
    COMMENT ON COLUMN public.fd_food_places.id IS '내부 음식 장소 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.fd_food_places.name IS '업소명';
    COMMENT ON COLUMN public.fd_food_places.business_category IS '원천 업종명';
    COMMENT ON COLUMN public.fd_food_places.normalized_category IS '서비스 표준 업종 분류';
    COMMENT ON COLUMN public.fd_food_places.is_course_food_candidate IS '코스 식사 후보 사용 여부';
    COMMENT ON COLUMN public.fd_food_places.address IS '주소';
    COMMENT ON COLUMN public.fd_food_places.tel IS '연락처';
    COMMENT ON COLUMN public.fd_food_places.business_hours_raw IS '원천 영업시간 문자열';
    COMMENT ON COLUMN public.fd_food_places.description IS '업소 소개';
    COMMENT ON COLUMN public.fd_food_places.representative_menu IS '대표 메뉴 문자열';
    COMMENT ON COLUMN public.fd_food_places.delivery_available IS '배달 가능 여부';
    COMMENT ON COLUMN public.fd_food_places.parking_available IS '주차 가능 여부';
    COMMENT ON COLUMN public.fd_food_places.source_region IS '원천 지역/구군명';
    COMMENT ON COLUMN public.fd_food_places.map_x IS '경도';
    COMMENT ON COLUMN public.fd_food_places.map_y IS '위도';
    COMMENT ON COLUMN public.fd_food_places.geog IS 'PostGIS geography 포인트(생성 컬럼)';
    COMMENT ON COLUMN public.fd_food_places.is_active IS '서비스 노출 활성 여부';
    COMMENT ON COLUMN public.fd_food_places.inactive_since IS '비활성 전환 시각';
    COMMENT ON COLUMN public.fd_food_places.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_places.created_by IS '생성 주체(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_places.updated_at IS '수정 시각(UpdateAudit)';
    COMMENT ON COLUMN public.fd_food_places.updated_by IS '수정 주체(UpdateAudit)';
    """)

    op.execute("""
    CREATE TABLE public.fd_food_place_sources (
        id              BIGSERIAL    PRIMARY KEY,
        food_place_id   BIGINT       NOT NULL
            REFERENCES public.fd_food_places(id) ON DELETE CASCADE,
        source          VARCHAR(40)  NOT NULL
            CHECK (source IN (
                'good_price_shop',
                'good_price_store',
                'good_price_menu',
                'good_price_file',
                'redtable',
                'busan_food',
                'model_restaurant',
                'admin_manual'
            )),
        external_id     VARCHAR(120) NOT NULL,
        source_region   VARCHAR(50),
        raw_json        JSONB        NOT NULL,
        fetched_at      TIMESTAMPTZ  NOT NULL,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        CONSTRAINT uk_fd_food_place_sources_source_external UNIQUE (source, external_id)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.fd_food_place_sources IS '음식 장소 외부 원천 식별자/원본 row';
    COMMENT ON COLUMN public.fd_food_place_sources.food_place_id IS '음식 장소 ID(FK)';
    COMMENT ON COLUMN public.fd_food_place_sources.source IS '원천 종류';
    COMMENT ON COLUMN public.fd_food_place_sources.external_id IS '원천별 식별자';
    COMMENT ON COLUMN public.fd_food_place_sources.source_region IS '원천 지역/구군명';
    COMMENT ON COLUMN public.fd_food_place_sources.raw_json IS '원천 응답 또는 파일 row(JSONB)';
    COMMENT ON COLUMN public.fd_food_place_sources.fetched_at IS '원천 수집 시각';
    COMMENT ON COLUMN public.fd_food_place_sources.created_at IS '행 생성 시각';
    """)

    op.execute("""
    CREATE TABLE public.fd_food_place_menus (
        id                  BIGSERIAL    PRIMARY KEY,
        food_place_id       BIGINT       NOT NULL
            REFERENCES public.fd_food_places(id) ON DELETE CASCADE,
        menu_name           VARCHAR(200) NOT NULL,
        price               INTEGER
            CHECK (price IS NULL OR price >= 0),
        currency            VARCHAR(3)   NOT NULL DEFAULT 'KRW',
        display_order       SMALLINT
            CHECK (display_order IS NULL OR display_order >= 1),
        source              VARCHAR(40)  NOT NULL
            CHECK (source IN (
                'good_price_menu',
                'good_price_file',
                'redtable',
                'admin_manual',
                'user_report',
                'crawler'
            )),
        is_representative   BOOLEAN      NOT NULL DEFAULT FALSE,
        last_observed_at    TIMESTAMPTZ,
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        created_by          VARCHAR(50),
        updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_by          VARCHAR(50),
        CONSTRAINT uk_fd_food_place_menus_place_name_source UNIQUE (food_place_id, menu_name, source)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.fd_food_place_menus IS '서비스 조회용 현재 메뉴/가격';
    COMMENT ON COLUMN public.fd_food_place_menus.food_place_id IS '음식 장소 ID(FK)';
    COMMENT ON COLUMN public.fd_food_place_menus.menu_name IS '메뉴/품목명';
    COMMENT ON COLUMN public.fd_food_place_menus.price IS '현재 가격';
    COMMENT ON COLUMN public.fd_food_place_menus.currency IS '통화 코드';
    COMMENT ON COLUMN public.fd_food_place_menus.display_order IS '원천 파일 품목 순서';
    COMMENT ON COLUMN public.fd_food_place_menus.source IS '현재 가격 원천';
    COMMENT ON COLUMN public.fd_food_place_menus.is_representative IS '대표 메뉴 여부';
    COMMENT ON COLUMN public.fd_food_place_menus.last_observed_at IS '가격 최종 관측 시각';
    COMMENT ON COLUMN public.fd_food_place_menus.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_place_menus.created_by IS '생성 주체(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_place_menus.updated_at IS '수정 시각(UpdateAudit)';
    COMMENT ON COLUMN public.fd_food_place_menus.updated_by IS '수정 주체(UpdateAudit)';
    """)

    op.execute("""
    CREATE TABLE public.fd_food_price_observations (
        id                  BIGSERIAL    PRIMARY KEY,
        food_place_id       BIGINT       NOT NULL
            REFERENCES public.fd_food_places(id) ON DELETE CASCADE,
        menu_name           VARCHAR(200) NOT NULL,
        observed_price      INTEGER      NOT NULL CHECK (observed_price >= 0),
        currency            VARCHAR(3)   NOT NULL DEFAULT 'KRW',
        display_order       SMALLINT
            CHECK (display_order IS NULL OR display_order >= 1),
        source_type         VARCHAR(20)  NOT NULL
            CHECK (source_type IN ('api', 'file_import', 'admin_manual', 'user_report', 'crawler')),
        source              VARCHAR(40)  NOT NULL
            CHECK (source IN (
                'good_price_menu',
                'good_price_file',
                'redtable',
                'admin_manual',
                'user_report',
                'crawler'
            )),
        raw_payload         JSONB,
        observed_at         TIMESTAMPTZ  NOT NULL,
        review_status       VARCHAR(20)  NOT NULL DEFAULT 'approved'
            CHECK (review_status IN ('pending', 'approved', 'rejected')),
        reviewed_by         BIGINT
            REFERENCES public.users(id) ON DELETE SET NULL,
        reviewed_at         TIMESTAMPTZ,
        reviewer_note       TEXT,
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        created_by          VARCHAR(50)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.fd_food_price_observations IS '메뉴 가격 관측/검수 이력';
    COMMENT ON COLUMN public.fd_food_price_observations.food_place_id IS '음식 장소 ID(FK)';
    COMMENT ON COLUMN public.fd_food_price_observations.menu_name IS '메뉴/품목명';
    COMMENT ON COLUMN public.fd_food_price_observations.observed_price IS '관측 가격';
    COMMENT ON COLUMN public.fd_food_price_observations.currency IS '통화 코드';
    COMMENT ON COLUMN public.fd_food_price_observations.display_order IS '원천 파일 품목 순서';
    COMMENT ON COLUMN public.fd_food_price_observations.source_type IS '관측 원천 타입';
    COMMENT ON COLUMN public.fd_food_price_observations.source IS '관측 원천';
    COMMENT ON COLUMN public.fd_food_price_observations.raw_payload IS '가격 관측 원본 row/payload(JSONB)';
    COMMENT ON COLUMN public.fd_food_price_observations.observed_at IS '가격 관측 시각';
    COMMENT ON COLUMN public.fd_food_price_observations.review_status IS '가격 검수 상태';
    COMMENT ON COLUMN public.fd_food_price_observations.reviewed_by IS '검수자 사용자 ID(FK)';
    COMMENT ON COLUMN public.fd_food_price_observations.reviewed_at IS '검수 시각';
    COMMENT ON COLUMN public.fd_food_price_observations.reviewer_note IS '검수 메모';
    COMMENT ON COLUMN public.fd_food_price_observations.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_price_observations.created_by IS '생성 주체(CreateAudit)';
    """)

    op.execute("""
    CREATE TABLE public.fd_food_place_spot_matches (
        id                  BIGSERIAL    PRIMARY KEY,
        food_place_id       BIGINT       NOT NULL
            REFERENCES public.fd_food_places(id) ON DELETE CASCADE,
        spot_content_id     VARCHAR(20)
            REFERENCES public.sp_spots(content_id) ON DELETE CASCADE,
        match_score         NUMERIC(4,3)
            CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 1)),
        match_status        VARCHAR(20)  NOT NULL DEFAULT 'pending'
            CHECK (match_status IN ('pending', 'matched', 'rejected', 'separate')),
        match_method        VARCHAR(20)
            CHECK (match_method IS NULL OR match_method IN ('rule', 'manual', 'llm')),
        reviewed_by         BIGINT
            REFERENCES public.users(id) ON DELETE SET NULL,
        reviewed_at         TIMESTAMPTZ,
        reviewer_note       TEXT,
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        created_by          VARCHAR(50),
        updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_by          VARCHAR(50),
        CONSTRAINT uk_fd_food_place_spot_matches_pair UNIQUE (food_place_id, spot_content_id),
        CONSTRAINT chk_fd_food_place_spot_matches_target
            CHECK (
                (match_status IN ('pending', 'matched', 'rejected') AND spot_content_id IS NOT NULL)
                OR
                (match_status = 'separate' AND spot_content_id IS NULL)
            )
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.fd_food_place_spot_matches IS '음식 장소와 TourAPI 스팟 매칭';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.food_place_id IS '음식 장소 ID(FK)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.spot_content_id IS 'TourAPI 스팟 content_id(FK)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.match_score IS '매칭 점수(0~1)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.match_status IS '매칭 상태';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.match_method IS '매칭 방식';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.reviewed_by IS '검수자 사용자 ID(FK)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.reviewed_at IS '검수 시각';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.reviewer_note IS '검수 메모';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.created_by IS '생성 주체(CreateAudit)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.updated_at IS '수정 시각(UpdateAudit)';
    COMMENT ON COLUMN public.fd_food_place_spot_matches.updated_by IS '수정 주체(UpdateAudit)';
    """)

    op.execute("""
    CREATE TABLE public.sp_spot_price_summary (
        spot_content_id             VARCHAR(20) PRIMARY KEY
            REFERENCES public.sp_spots(content_id) ON DELETE CASCADE,
        min_price                   INTEGER
            CHECK (min_price IS NULL OR min_price >= 0),
        avg_price                   INTEGER
            CHECK (avg_price IS NULL OR avg_price >= 0),
        representative_menu_name    VARCHAR(200),
        representative_price        INTEGER
            CHECK (representative_price IS NULL OR representative_price >= 0),
        menu_count                  INTEGER      NOT NULL DEFAULT 0
            CHECK (menu_count >= 0),
        source_count                INTEGER      NOT NULL DEFAULT 0
            CHECK (source_count >= 0),
        updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.sp_spot_price_summary IS '코스 추천 조회 최적화용 스팟 가격 요약 캐시';
    COMMENT ON COLUMN public.sp_spot_price_summary.spot_content_id IS 'TourAPI 스팟 content_id(PK/FK)';
    COMMENT ON COLUMN public.sp_spot_price_summary.min_price IS '최저 메뉴 가격';
    COMMENT ON COLUMN public.sp_spot_price_summary.avg_price IS '평균 메뉴 가격';
    COMMENT ON COLUMN public.sp_spot_price_summary.representative_menu_name IS '대표 메뉴명';
    COMMENT ON COLUMN public.sp_spot_price_summary.representative_price IS '대표 메뉴 가격';
    COMMENT ON COLUMN public.sp_spot_price_summary.menu_count IS '가격 보유 메뉴 수';
    COMMENT ON COLUMN public.sp_spot_price_summary.source_count IS '가격 원천 수';
    COMMENT ON COLUMN public.sp_spot_price_summary.updated_at IS '요약 갱신 시각';
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_places_geog_active
        ON public.fd_food_places USING gist (geog)
        WHERE is_active = TRUE AND geog IS NOT NULL;
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_places_category_active
        ON public.fd_food_places (normalized_category, source_region)
        WHERE is_active = TRUE;
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_place_menus_place_price
        ON public.fd_food_place_menus (food_place_id, price);
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_price_observations_place_created
        ON public.fd_food_price_observations (food_place_id, created_at DESC);
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_price_observations_pending_created
        ON public.fd_food_price_observations (created_at DESC)
        WHERE review_status = 'pending';
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_place_matches_spot_status
        ON public.fd_food_place_spot_matches (spot_content_id, match_status);
    """)

    op.execute("""
    CREATE INDEX idx_fd_food_place_matches_food_place
        ON public.fd_food_place_spot_matches (food_place_id);
    """)

    op.execute("""
    CREATE UNIQUE INDEX uk_fd_food_place_matches_separate
        ON public.fd_food_place_spot_matches (food_place_id)
        WHERE match_status = 'separate';
    """)

    op.execute("""
    CREATE INDEX idx_sp_spot_price_summary_min_price
        ON public.sp_spot_price_summary (min_price)
        WHERE min_price IS NOT NULL;
    """)

    for table in ("fd_food_places", "fd_food_place_menus", "fd_food_place_spot_matches"):
        op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON public.{table}
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
        """)


def downgrade() -> None:
    for table in ("fd_food_place_spot_matches", "fd_food_place_menus", "fd_food_places"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON public.{table};")

    op.execute("DROP INDEX IF EXISTS public.idx_sp_spot_price_summary_min_price;")
    op.execute("DROP INDEX IF EXISTS public.uk_fd_food_place_matches_separate;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_place_matches_food_place;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_place_matches_spot_status;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_price_observations_pending_created;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_price_observations_place_created;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_place_menus_place_price;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_places_category_active;")
    op.execute("DROP INDEX IF EXISTS public.idx_fd_food_places_geog_active;")
    op.execute("DROP TABLE IF EXISTS public.sp_spot_price_summary;")
    op.execute("DROP TABLE IF EXISTS public.fd_food_place_spot_matches;")
    op.execute("DROP TABLE IF EXISTS public.fd_food_price_observations;")
    op.execute("DROP TABLE IF EXISTS public.fd_food_place_menus;")
    op.execute("DROP TABLE IF EXISTS public.fd_food_place_sources;")
    op.execute("DROP TABLE IF EXISTS public.fd_food_places;")

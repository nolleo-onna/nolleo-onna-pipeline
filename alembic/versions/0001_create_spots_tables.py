"""spots core tables: spots_core + spot_details (Hot/Cold 1:1)

operation.md §1#1 / §3 / §11.
이 단계에서 깨지면 이후 모든 SPOTS 마이그레이션이 진행 불가.
확장은 사전 프로비저닝 가정, 여기선 검증만.

Revision ID: 0001_spots_core_tables
Revises:
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op

revision = "0001_spots_core_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) 확장 사전 검증
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
            RAISE EXCEPTION 'extension "postgis" is required. '
                'Run scripts/db/00_provision_extensions.sql first.';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            RAISE EXCEPTION 'extension "vector" is required. '
                'Run scripts/db/00_provision_extensions.sql first.';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
            RAISE EXCEPTION 'extension "pg_trgm" is required. '
                'Run scripts/db/00_provision_extensions.sql first.';
        END IF;
    END
    $$;
    """)

    # 1) spots_core (핫패스 메인 테이블)
    op.execute("""
    CREATE TABLE spots_core (
        content_id                  VARCHAR(20)  PRIMARY KEY,
        content_type_id             VARCHAR(8)   NOT NULL
            CHECK (content_type_id IN ('12','14','39')),
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

        overview_summary            TEXT,
        price_level                 SMALLINT     CHECK (price_level BETWEEN 0 AND 3),
        price_text                  VARCHAR(50),
        indoor                      BOOLEAN,
        is_good_price               BOOLEAN      NOT NULL DEFAULT FALSE,

        today_concentration_rate    NUMERIC(5,2),
        upcoming_concentration_avg  NUMERIC(5,2),
        concentration_updated_at    TIMESTAMPTZ,
        trend_score                 NUMERIC(6,3),
        gem_score                   NUMERIC(6,3),
        trend_updated_at            TIMESTAMPTZ,
        popularity_score            NUMERIC(6,3),
        avg_rating                  NUMERIC(3,2)
            CHECK (avg_rating IS NULL OR (avg_rating >= 0 AND avg_rating <= 5)),
        review_count                INTEGER      NOT NULL DEFAULT 0,
        rating_updated_at           TIMESTAMPTZ,

        source_modified_time        TIMESTAMPTZ,
        synced_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

        is_active                   BOOLEAN      NOT NULL DEFAULT TRUE,
        inactive_since              TIMESTAMPTZ,

        CONSTRAINT chk_spots_core_map_x_range
            CHECK (map_x IS NULL OR map_x BETWEEN -180 AND 180),
        CONSTRAINT chk_spots_core_map_y_range
            CHECK (map_y IS NULL OR map_y BETWEEN -90 AND 90)
    );
    """)

    # 2) spot_details (콜드 1:1)
    op.execute("""
    CREATE TABLE spot_details (
        content_id                      VARCHAR(20) PRIMARY KEY
            REFERENCES spots_core(content_id) ON DELETE CASCADE,

        tel                             VARCHAR(50),
        homepage                        TEXT,
        addr1                           TEXT,
        addr2                           TEXT,
        zipcode                         VARCHAR(10),

        overview                        TEXT,
        overview_hash                   VARCHAR(64),

        intro                           JSONB,

        business_hours                  JSONB,
        business_hours_source           VARCHAR(20)
            CHECK (business_hours_source IN
                   ('tourapi_raw','llm_auto','llm_verified','manual')),
        business_hours_confidence       NUMERIC(4,3)
            CHECK (business_hours_confidence IS NULL OR
                   (business_hours_confidence >= 0 AND business_hours_confidence <= 1)),
        business_hours_model            VARCHAR(80),
        business_hours_parsed_at        TIMESTAMPTZ,
        business_hours_verified_at      TIMESTAMPTZ,
        business_hours_stale_after      TIMESTAMPTZ,

        parking_available               BOOLEAN,
        created_time                    TIMESTAMPTZ,
        updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spot_details;")
    op.execute("DROP TABLE IF EXISTS spots_core;")
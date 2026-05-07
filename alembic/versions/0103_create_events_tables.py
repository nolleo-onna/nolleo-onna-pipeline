"""create events domain tables (core/details/embeddings/raw/images)

operation.md §3 행사 도메인 / ERD §EVENTS_*.

설계 포인트:
- SPOTS와 동일 패턴 (Hot/Cold 1:1, 임베딩 1:1, RAW 1:1, 이미지 1:N).
- EVENTS_CORE.event_period: daterange GENERATED ALWAYS (`[start, end]` inclusive).
- venue_spot_id: SPOTS_CORE 매칭 결과 (NULL = 매칭 없음 또는 일반 장소). ON DELETE SET NULL
  — 행사장 스팟이 삭제되어도 행사 자체는 보존.
- expected_concentration_source: rule/llm/manual 추적 (festival_grade 기반).
- 종료 행사 자동 비활성화 cron 대상은 is_active 컬럼 기준.

FK 부착:
- events_core.(l_dong_regn_cd, l_dong_signgu_cd) → ldong_codes (즉시 인라인)
- events_core.venue_spot_id → spots_core (즉시 인라인, 양쪽 다 존재)

Revision ID: 0103_create_events_tables
Revises: 0102_create_good_price_locale_codes
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0103_create_events_tables"
down_revision = "0102_create_gp_locale_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) EVENTS_CORE
    op.execute("""
    CREATE TABLE events_core (
        content_id                     VARCHAR(20) PRIMARY KEY,
        title                          VARCHAR(200) NOT NULL,

        map_x                          NUMERIC(10,7),
        map_y                          NUMERIC(10,7),
        geog                           geography(POINT, 4326) GENERATED ALWAYS AS (
            CASE
                WHEN map_x IS NOT NULL AND map_y IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint(map_x, map_y), 4326)::geography
                ELSE NULL
            END
        ) STORED,

        l_dong_regn_cd                 VARCHAR(2),
        l_dong_signgu_cd               VARCHAR(5),

        first_image                    TEXT,
        first_image2                   TEXT,

        event_start_date               DATE NOT NULL,
        event_end_date                 DATE NOT NULL,
        event_period                   daterange GENERATED ALWAYS AS (
            daterange(event_start_date, event_end_date, '[]')
        ) STORED,

        event_place                    TEXT,
        festival_grade                 VARCHAR(20),

        venue_spot_id                  VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE SET NULL,

        overview_summary               TEXT,
        indoor                         BOOLEAN,
        expected_concentration         NUMERIC(5,2)
            CHECK (expected_concentration IS NULL OR
                   (expected_concentration >= 0 AND expected_concentration <= 100)),
        expected_concentration_source  VARCHAR(20)
            CHECK (expected_concentration_source IS NULL OR
                   expected_concentration_source IN ('rule','llm','manual')),

        source_modified_time           TIMESTAMPTZ,
        synced_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        is_active                      BOOLEAN NOT NULL DEFAULT TRUE,
        inactive_since                 TIMESTAMPTZ,

        CONSTRAINT chk_events_core_date_range
            CHECK (event_end_date >= event_start_date),
        CONSTRAINT chk_events_core_map_x
            CHECK (map_x IS NULL OR map_x BETWEEN -180 AND 180),
        CONSTRAINT chk_events_core_map_y
            CHECK (map_y IS NULL OR map_y BETWEEN -90 AND 90),
        CONSTRAINT fk_events_core_signgu
            FOREIGN KEY (l_dong_regn_cd, l_dong_signgu_cd)
            REFERENCES ldong_codes(regn_cd, signgu_cd)
            ON UPDATE CASCADE ON DELETE RESTRICT
    );
    """)

    # 2) EVENT_DETAILS (Cold 1:1)
    op.execute("""
    CREATE TABLE event_details (
        content_id           VARCHAR(20) PRIMARY KEY
            REFERENCES events_core(content_id) ON DELETE CASCADE,
        addr1                TEXT,
        addr2                TEXT,
        tel                  VARCHAR(50),
        homepage             TEXT,
        overview             TEXT,
        overview_hash        VARCHAR(64),
        play_time            VARCHAR(200),
        use_time_festival    TEXT,
        age_limit            VARCHAR(50),
        booking_place        VARCHAR(200),
        program              TEXT,
        sub_event            TEXT,
        sponsor1             VARCHAR(200),
        sponsor1_tel         VARCHAR(50),
        sponsor2             VARCHAR(200),
        sponsor2_tel         VARCHAR(50),
        spendtime_festival   VARCHAR(100),
        place_info           TEXT,
        discount_info        TEXT,
        created_time         TIMESTAMPTZ,
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 3) EVENT_EMBEDDINGS (1:1)
    op.execute("""
    CREATE TABLE event_embeddings (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES events_core(content_id) ON DELETE CASCADE,
        embedding       vector(1536) NOT NULL,
        source_text     TEXT         NOT NULL,
        source_hash     VARCHAR(64)  NOT NULL,
        model_name      VARCHAR(80)  NOT NULL,
        model_version   VARCHAR(40)  NOT NULL,
        token_count     INTEGER      NOT NULL CHECK (token_count >= 0),
        embedded_at     TIMESTAMPTZ  NOT NULL,
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    """)

    # 4) EVENTS_RAW_SNAPSHOTS (1:1, 최신만 UPSERT)
    op.execute("""
    CREATE TABLE events_raw_snapshots (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES events_core(content_id) ON DELETE CASCADE,
        raw_json        JSONB       NOT NULL,
        fetched_at      TIMESTAMPTZ NOT NULL,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 5) EVENT_IMAGES (1:N, REPLACE 패턴)
    op.execute("""
    CREATE TABLE event_images (
        id              BIGSERIAL    PRIMARY KEY,
        content_id      VARCHAR(20)  NOT NULL
            REFERENCES events_core(content_id) ON DELETE CASCADE,
        origin_img_url  TEXT         NOT NULL,
        small_img_url   TEXT,
        img_name        VARCHAR(200),
        serial_num      VARCHAR(20)  NOT NULL,
        CONSTRAINT uk_event_images_content_serial UNIQUE (content_id, serial_num)
    );
    """)

    # 6) 인덱스
    # Q5: 오늘 행사 (홈 화면). event_period GiST + is_active partial.
    op.execute("""
    CREATE INDEX idx_events_period_gist
        ON events_core USING gist (event_period)
        WHERE is_active = true;
    """)

    # 시군구 필터 + 시작일 정렬
    op.execute("""
    CREATE INDEX idx_events_signgu_start
        ON events_core (l_dong_signgu_cd, event_start_date DESC)
        WHERE is_active = true;
    """)

    # 자연어 검색 (의미)
    op.execute("""
    CREATE INDEX idx_event_embeddings_hnsw
        ON event_embeddings USING hnsw (embedding vector_cosine_ops);
    """)

    # 7) updated_at 트리거 부착
    for table in ("events_core", "event_details", "event_embeddings", "events_raw_snapshots"):
        op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    for table in ("events_raw_snapshots", "event_embeddings", "event_details", "events_core"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute("DROP INDEX IF EXISTS idx_event_embeddings_hnsw;")
    op.execute("DROP INDEX IF EXISTS idx_events_signgu_start;")
    op.execute("DROP INDEX IF EXISTS idx_events_period_gist;")
    op.execute("DROP TABLE IF EXISTS event_images;")
    op.execute("DROP TABLE IF EXISTS events_raw_snapshots;")
    op.execute("DROP TABLE IF EXISTS event_embeddings;")
    op.execute("DROP TABLE IF EXISTS event_details;")
    op.execute("DROP TABLE IF EXISTS events_core;")

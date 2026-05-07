"""create good_price domain tables (shops/raw/match_queue/shop_prices/price_observations)

operation.md §3 착한가격 도메인 / ERD §GOOD_PRICE_*.

설계 포인트:
- GOOD_PRICE_SHOPS: 부산 ~600건. 좌표 부재 → 카카오 지오코딩.
- match_status: pending / matched / unmatched / separate
- matched_spot_id 단방향 SoT (SPOTS_CORE.good_price_shop_id 미도입 — 확정).
- 음식점(602)만 SPOTS_CORE 연결, 이미용/목욕(603/604)은 GOOD_PRICE_SHOPS만 보관.
- 가격모델 2층화 (ADR 0002):
  - SHOP_PRICES: 조회용 "현재 확정가" SoT (Spring RW)
  - PRICE_OBSERVATIONS: append-only 이력 + 검수 (Spring RW)
- 순환 참조 방지: SHOP_PRICES.current_price_observation_id 단방향만.
  PRICE_OBSERVATIONS.shop_price_id 미도입.

USERS 미존재 시점 → submitter_user_id / reviewed_by 컬럼은 두되, FK는 후속(0112)에서 부착.

Revision ID: 0105_create_good_price_tables
Revises: 0104_create_travel_courses_tables
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0105_create_good_price_tables"
down_revision = "0104_create_travel_courses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) GOOD_PRICE_SHOPS
    op.execute("""
    CREATE TABLE good_price_shops (
        id                       BIGSERIAL    PRIMARY KEY,
        external_id              VARCHAR(50)  NOT NULL UNIQUE,
        name                     VARCHAR(200) NOT NULL,
        owner_name               VARCHAR(100),
        addr                     TEXT,
        tel                      VARCHAR(50),
        category_code            VARCHAR(10)
            CHECK (category_code IS NULL OR category_code IN ('602','603','604')),
        category_name            VARCHAR(50),
        locale_code              VARCHAR(20)
            REFERENCES good_price_locale_codes(locale_cd)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        locale_name              VARCHAR(100),
        l_dong_signgu_cd         VARCHAR(5),
        intro_html               TEXT,
        intro_text               TEXT,
        business_hours_raw       VARCHAR(500),
        business_hours_parsed    JSONB,
        has_parking              BOOLEAN,
        img_file1                TEXT,
        img_name1                VARCHAR(200),
        img_file2                TEXT,
        img_name2                VARCHAR(200),

        map_x                    NUMERIC(10,7),
        map_y                    NUMERIC(10,7),
        geog                     geography(POINT, 4326) GENERATED ALWAYS AS (
            CASE
                WHEN map_x IS NOT NULL AND map_y IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint(map_x, map_y), 4326)::geography
                ELSE NULL
            END
        ) STORED,
        geocoded_at              TIMESTAMPTZ,
        geocoded_source          VARCHAR(20)
            CHECK (geocoded_source IS NULL OR geocoded_source IN ('kakao','naver')),
        geocode_failed           BOOLEAN NOT NULL DEFAULT FALSE,

        match_status             VARCHAR(20) NOT NULL DEFAULT 'pending'
            CHECK (match_status IN ('pending','matched','unmatched','separate')),
        matched_spot_id          VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE SET NULL,

        source_created_at        TIMESTAMPTZ,
        synced_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        is_active                BOOLEAN NOT NULL DEFAULT TRUE,
        inactive_since           TIMESTAMPTZ,

        CONSTRAINT chk_good_price_shops_map_x
            CHECK (map_x IS NULL OR map_x BETWEEN -180 AND 180),
        CONSTRAINT chk_good_price_shops_map_y
            CHECK (map_y IS NULL OR map_y BETWEEN -90 AND 90)
    );
    """)

    # 2) GPS_RAW_SNAPSHOTS (1:1)
    op.execute("""
    CREATE TABLE gps_raw_snapshots (
        shop_id     BIGINT      PRIMARY KEY
            REFERENCES good_price_shops(id) ON DELETE CASCADE,
        raw_json    JSONB       NOT NULL,
        fetched_at  TIMESTAMPTZ NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 3) GOOD_PRICE_MATCH_QUEUE
    #    reviewed_by → users 는 후속(0112) 부착.
    op.execute("""
    CREATE TABLE good_price_match_queue (
        id                   BIGSERIAL    PRIMARY KEY,
        shop_id              BIGINT       NOT NULL
            REFERENCES good_price_shops(id) ON DELETE CASCADE,
        candidate_spot_id    VARCHAR(20)  NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        match_score          NUMERIC(4,3) NOT NULL CHECK (match_score >= 0 AND match_score <= 1),
        phone_score          NUMERIC(4,3),
        name_score           NUMERIC(4,3),
        address_score        NUMERIC(4,3),
        distance_m           NUMERIC(8,2),
        signal_details       JSONB,
        match_status         VARCHAR(20)  NOT NULL DEFAULT 'pending'
            CHECK (match_status IN ('pending','approved','rejected')),
        reviewed_by          BIGINT,                  -- FK 후속 부착
        reviewed_at          TIMESTAMPTZ,
        reviewer_note        TEXT,
        created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        CONSTRAINT uk_match_queue_shop_candidate
            UNIQUE (shop_id, candidate_spot_id)
    );
    """)

    # 4) GOOD_PRICE_SHOP_PRICES
    #    current_price_observation_id 단방향 (FK는 다음 테이블 생성 후 부착).
    op.execute("""
    CREATE TABLE good_price_shop_prices (
        id                            BIGSERIAL    PRIMARY KEY,
        shop_id                       BIGINT       NOT NULL
            REFERENCES good_price_shops(id) ON DELETE CASCADE,
        item_name                     VARCHAR(200) NOT NULL,
        current_price                 NUMERIC(12,2) NOT NULL CHECK (current_price >= 0),
        currency                      VARCHAR(3)   NOT NULL DEFAULT 'KRW',
        unit                          VARCHAR(50),
        last_observed_at              TIMESTAMPTZ  NOT NULL,
        last_verified_at              TIMESTAMPTZ,
        current_price_observation_id  BIGINT,                -- FK는 5) 생성 후 부착
        updated_at                    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        CONSTRAINT uk_shop_prices_shop_item UNIQUE (shop_id, item_name)
    );
    """)

    # 5) GOOD_PRICE_PRICE_OBSERVATIONS (append-only)
    op.execute("""
    CREATE TABLE good_price_price_observations (
        id                BIGSERIAL    PRIMARY KEY,
        shop_id           BIGINT       NOT NULL
            REFERENCES good_price_shops(id) ON DELETE CASCADE,
        source_type       VARCHAR(20)  NOT NULL
            CHECK (source_type IN ('admin_manual','user_report','crawler')),
        submitter_user_id BIGINT,                            -- FK 후속 부착
        item_name         VARCHAR(200) NOT NULL,
        reported_price    NUMERIC(12,2) NOT NULL CHECK (reported_price >= 0),
        currency          VARCHAR(3)   NOT NULL DEFAULT 'KRW',
        unit              VARCHAR(50),
        observed_at       TIMESTAMPTZ  NOT NULL,
        evidence_type     VARCHAR(20)
            CHECK (evidence_type IS NULL OR evidence_type IN ('receipt','photo','text','none')),
        evidence_ref      TEXT,
        report_status     VARCHAR(20)  NOT NULL DEFAULT 'pending'
            CHECK (report_status IN ('pending','approved','rejected')),
        reviewed_by       BIGINT,                            -- FK 후속 부착
        reviewed_at       TIMESTAMPTZ,
        reviewer_note     TEXT,
        raw_payload       JSONB,
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    """)

    # 6) shop_prices.current_price_observation_id → price_observations 단방향 FK.
    op.execute("""
    ALTER TABLE good_price_shop_prices
      ADD CONSTRAINT fk_shop_prices_observation
      FOREIGN KEY (current_price_observation_id)
      REFERENCES good_price_price_observations(id)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)

    # 7) 인덱스
    # 매칭 큐 검수 화면
    op.execute("""
    CREATE INDEX idx_match_queue_status_created
        ON good_price_match_queue (match_status, created_at DESC)
        WHERE match_status = 'pending';
    """)

    # 가격 관측 검수 화면
    op.execute("""
    CREATE INDEX idx_price_observations_status_created
        ON good_price_price_observations (report_status, created_at DESC)
        WHERE report_status = 'pending';
    """)

    # 지도 마커 (음식점 + 활성 + 좌표 있음)
    op.execute("""
    CREATE INDEX idx_good_price_shops_geog_active
        ON good_price_shops USING gist (geog)
        WHERE is_active = true AND geog IS NOT NULL;
    """)

    # 시군구별 조회
    op.execute("""
    CREATE INDEX idx_good_price_shops_signgu
        ON good_price_shops (l_dong_signgu_cd)
        WHERE is_active = true;
    """)

    # 8) updated_at 트리거
    for table in ("good_price_shops", "gps_raw_snapshots", "good_price_shop_prices"):
        op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    for table in ("good_price_shop_prices", "gps_raw_snapshots", "good_price_shops"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute("DROP INDEX IF EXISTS idx_good_price_shops_signgu;")
    op.execute("DROP INDEX IF EXISTS idx_good_price_shops_geog_active;")
    op.execute("DROP INDEX IF EXISTS idx_price_observations_status_created;")
    op.execute("DROP INDEX IF EXISTS idx_match_queue_status_created;")
    op.execute("""
    ALTER TABLE good_price_shop_prices
      DROP CONSTRAINT IF EXISTS fk_shop_prices_observation;
    """)
    op.execute("DROP TABLE IF EXISTS good_price_price_observations;")
    op.execute("DROP TABLE IF EXISTS good_price_shop_prices;")
    op.execute("DROP TABLE IF EXISTS good_price_match_queue;")
    op.execute("DROP TABLE IF EXISTS gps_raw_snapshots;")
    op.execute("DROP TABLE IF EXISTS good_price_shops;")

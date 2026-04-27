"""spots peripheral tables: embeddings / raw / images / tags / congestion

각 테이블은 spots_core를 부모로 하는 1:1 또는 1:N.
자연 식별자 UK는 "테이블 정의의 일부"라 0003이 아니라 여기서 같이 만든다.

리뷰 반영:
- spot_tags PK = (content_id, tag_id, source) — manual/llm 공존
- spot_congestion_forecast — matched/unmatched partial UK 분리
- ADR 0001: spot_congestion_forecast.trace jsonb로 LLM 매칭 추적
- concentration_rate 0~100 CHECK / raw_tats_name 길이 100

Revision ID: 0002_spots_peripheral_tables
Revises: 0001_spots_core_tables
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op

revision = "0002_spots_peripheral_tables"
down_revision = "0001_spots_core_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) SPOT_EMBEDDINGS — pgvector 1536 (text-embedding-3-small).
    op.execute("""
    CREATE TABLE spot_embeddings (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES spots_core(content_id) ON DELETE CASCADE,

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

    # 2) SPOTS_RAW_SNAPSHOTS — 4개 endpoint 통합 raw_json (UPSERT, 최신만).
    op.execute("""
    CREATE TABLE spots_raw_snapshots (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES spots_core(content_id) ON DELETE CASCADE,

        raw_json        JSONB       NOT NULL,
        fetched_at      TIMESTAMPTZ NOT NULL,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 3) SPOT_IMAGES — 갤러리 N장. §2 REPLACE / §14 단일 트랜잭션.
    op.execute("""
    CREATE TABLE spot_images (
        id              BIGSERIAL    PRIMARY KEY,
        content_id      VARCHAR(20)  NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        origin_img_url  TEXT         NOT NULL,
        small_img_url   TEXT,
        img_name        VARCHAR(200),
        serial_num      VARCHAR(20)  NOT NULL,
        CONSTRAINT uk_spot_images_content_serial UNIQUE (content_id, serial_num)
    );
    """)

    # 4) SPOT_TAGS — source='llm'만 REPLACE, manual 보존. PK에 source 포함.
    op.execute("""
    CREATE TABLE spot_tags (
        content_id      VARCHAR(20)  NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        tag_id          SMALLINT     NOT NULL,
        source          VARCHAR(10)  NOT NULL
            CHECK (source IN ('llm','rule','manual')),
        score           NUMERIC(4,3) NOT NULL CHECK (score >= 0 AND score <= 1),
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        PRIMARY KEY (content_id, tag_id, source)
    );
    """)

    # 5) SPOT_CONGESTION_FORECAST
    #    - content_id NULL 허용(매칭 실패)
    #    - matched/unmatched partial UK 2개 분리
    #    - trace JSONB: ADR 0001에 따라 LLM 매칭 추적 정보 저장
    #      예: {"model_name":"gpt-4o-mini","model_version":"2024-07-18",
    #           "prompt_version":"v1","source_text_hash":"...","confidence":0.92}
    #    - source='tourapi'/'rule'이면 trace는 NULL
    op.execute("""
    CREATE TABLE spot_congestion_forecast (
        id                  BIGSERIAL    PRIMARY KEY,
        content_id          VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE SET NULL,
        area_cd             VARCHAR(2)   NOT NULL,
        signgu_cd           VARCHAR(5)   NOT NULL,
        raw_tats_name       VARCHAR(100) NOT NULL,
        area_name           VARCHAR(100),
        signgu_name         VARCHAR(100),
        base_ymd            DATE         NOT NULL,
        concentration_rate  NUMERIC(5,2) NOT NULL
            CHECK (concentration_rate BETWEEN 0 AND 100),
        level               SMALLINT     NOT NULL CHECK (level BETWEEN 1 AND 5),
        source              VARCHAR(20)  NOT NULL
            CHECK (source IN ('tourapi','llm','rule')),
        trace               JSONB,
        fetched_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

        -- source='llm'이면 trace 필수, 아니면 NULL이어야 정상.
        CONSTRAINT chk_spot_congestion_trace_consistency
            CHECK (
                (source = 'llm' AND trace IS NOT NULL)
                OR (source <> 'llm' AND trace IS NULL)
            )
    );
    """)

    # matched 행: content_id 기준 자연키
    op.execute("""
    CREATE UNIQUE INDEX uk_spot_congestion_matched
        ON spot_congestion_forecast (content_id, base_ymd, source)
        WHERE content_id IS NOT NULL;
    """)

    # unmatched 행: TourAPI 원본 식별자 기준
    op.execute("""
    CREATE UNIQUE INDEX uk_spot_congestion_unmatched
        ON spot_congestion_forecast (area_cd, signgu_cd, raw_tats_name, base_ymd, source)
        WHERE content_id IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spot_congestion_forecast;")
    op.execute("DROP TABLE IF EXISTS spot_tags;")
    op.execute("DROP TABLE IF EXISTS spot_images;")
    op.execute("DROP TABLE IF EXISTS spots_raw_snapshots;")
    op.execute("DROP TABLE IF EXISTS spot_embeddings;")
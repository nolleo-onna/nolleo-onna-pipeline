"""create weather_cache (기상청 단기예보 시계열 캐시)

operation.md §3 코드/날씨 마스터 #WEATHER_CACHE / ERD §WEATHER_CACHE.

- TTL: 15분 (`expires_at = fetched_at + 15분`)
- 기상청 표준 코드:
  - pty (강수형태): 0/1/2/3/5/6/7
  - sky_condition (하늘상태): 1/3/4
- 미래 24시간 예보 보관, 과거 7일 후 cron 삭제.
- 코스 생성 시점 날씨는 GENERATED_COURSES.weather_at_gen JSONB 별도 스냅샷.

Revision ID: 0101_create_weather_cache
Revises: 0100_create_weather_grids
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0101_create_weather_cache"
down_revision = "0100_create_weather_grids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE weather_cache (
        id              BIGSERIAL    PRIMARY KEY,
        signgu_cd       VARCHAR(5)   NOT NULL
            REFERENCES weather_grids(signgu_cd)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        observed_at     TIMESTAMPTZ  NOT NULL,
        rain_prob       INTEGER
            CHECK (rain_prob IS NULL OR (rain_prob >= 0 AND rain_prob <= 100)),
        temperature     NUMERIC(4,1),
        sky_condition   VARCHAR(2)
            CHECK (sky_condition IS NULL OR sky_condition IN ('1','3','4')),
        pty             VARCHAR(2)
            CHECK (pty IS NULL OR pty IN ('0','1','2','3','5','6','7')),
        fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        expires_at      TIMESTAMPTZ  NOT NULL
    );
    """)

    # 핫패스: 시군구 + 예보시각 조회 (코스 생성 시 날씨 lookup)
    op.execute("""
    CREATE INDEX idx_weather_cache_signgu_observed
        ON weather_cache (signgu_cd, observed_at);
    """)

    # 만료 청소 cron 인덱스
    op.execute("""
    CREATE INDEX idx_weather_cache_expires
        ON weather_cache (expires_at);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_weather_cache_expires;")
    op.execute("DROP INDEX IF EXISTS idx_weather_cache_signgu_observed;")
    op.execute("DROP TABLE IF EXISTS weather_cache;")

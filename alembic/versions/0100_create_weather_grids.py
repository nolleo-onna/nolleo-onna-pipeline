"""create weather_grids (시군구별 기상청 LCC 격자 좌표 마스터)

operation.md §3 코드/날씨 마스터 #WEATHER_GRIDS / ERD §WEATHER_GRIDS.

- 부산 16개 시군구 격자 좌표 시드 등록 (운영 시드 스크립트로).
- LDONG_CODES.signgu_cd 를 참조 (regn_cd='26' 부산만 다루므로 signgu_cd 단독 충분).
  단, ldong_codes PK가 (regn_cd, signgu_cd) 복합이라 단독 FK는 불가.
  → 해결: weather_grids에 regn_cd도 함께 두고 복합 FK로 부착.
- 시군구 단위 거시 날씨로 충분 (스팟 단위 정밀 날씨 미적용).

Revision ID: 0100_create_weather_grids
Revises: 0099_spots_external_fks
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0100_create_weather_grids"
down_revision = "0099_spots_external_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE weather_grids (
        regn_cd      VARCHAR(2)   NOT NULL,
        signgu_cd    VARCHAR(5)   PRIMARY KEY,
        signgu_name  VARCHAR(100) NOT NULL,
        center_lat   NUMERIC(10,7) NOT NULL,
        center_lon   NUMERIC(10,7) NOT NULL,
        kma_nx       INTEGER      NOT NULL,
        kma_ny       INTEGER      NOT NULL,
        CONSTRAINT chk_weather_grids_lat CHECK (center_lat BETWEEN -90 AND 90),
        CONSTRAINT chk_weather_grids_lon CHECK (center_lon BETWEEN -180 AND 180),
        CONSTRAINT fk_weather_grids_signgu
            FOREIGN KEY (regn_cd, signgu_cd)
            REFERENCES ldong_codes(regn_cd, signgu_cd)
            ON UPDATE CASCADE ON DELETE RESTRICT
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weather_grids;")

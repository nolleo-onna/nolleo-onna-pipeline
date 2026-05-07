"""create ldong_codes (TourAPI 법정동 마스터)

operation.md §3 코드/날씨 마스터 / ERD §LDONG_CODES.

- 모든 도메인의 지역 코드 SoT.
  SPOTS_CORE / EVENTS_CORE / GOOD_PRICE_LOCALE_CODES / WEATHER_GRIDS /
  SPOT_CONGESTION_FORECAST 가 이 테이블을 FK로 참조.
- (regn_cd, signgu_cd) 복합 PK. TourAPI lDongRegnCd / lDongSignguCd 형식.
- 부산 16개 시군구 시드는 운영 시드 스크립트에서 별도 처리. 마이그레이션은 DDL만.

Revision ID: 0006_create_ldong_codes
Revises: 0005_create_sync_logs
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0006_create_ldong_codes"
down_revision = "0005_create_sync_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ldong_codes (
        regn_cd     VARCHAR(2)   NOT NULL,
        signgu_cd   VARCHAR(5)   NOT NULL,
        name        VARCHAR(100) NOT NULL,
        PRIMARY KEY (regn_cd, signgu_cd)
    );
    """)


def downgrade() -> None:
    # 0099 같은 후행 마이그레이션이 부착한 FK가 먼저 풀려야 안전하게 DROP 가능.
    op.execute("DROP TABLE IF EXISTS ldong_codes;")

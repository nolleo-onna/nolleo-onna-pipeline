"""create lcls_systm_codes (TourAPI 분류체계 마스터)

operation.md §3 코드/날씨 마스터 / ERD §LCLS_SYSTM_CODES.

- TourAPI 대/중/소분류 3단 (lclsSystm1/2/3) 마스터.
- (code1, code2, code3) 복합 PK.
- SPOTS_CORE.lcls_systm_1/2/3 가 복합 FK로 참조 (0099에서 부착).
- 시드는 TourAPI 코드조회 endpoint 응답에서 동적으로 채움 (~수백 row).

Revision ID: 0007_create_lcls_systm_codes
Revises: 0006_create_ldong_codes
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0007_create_lcls_systm_codes"
down_revision = "0006_create_ldong_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE lcls_systm_codes (
        code1   VARCHAR(10)  NOT NULL,
        code2   VARCHAR(10)  NOT NULL,
        code3   VARCHAR(10)  NOT NULL,
        name    VARCHAR(200) NOT NULL,
        PRIMARY KEY (code1, code2, code3)
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lcls_systm_codes;")

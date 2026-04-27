"""spots external FK attachments (after master tables land)

부착 대상:
- spots_core.l_dong_regn_cd / l_dong_signgu_cd → LDONG_CODES
- spots_core.lcls_systm_1/2/3                  → LCLS_SYSTM_CODES (복합키)
- spot_tags.tag_id                             → TAGS
- spot_congestion_forecast.signgu_cd           → LDONG_CODES

이 마이그레이션은 master 테이블 존재가 전제. master 마이그레이션 revision이 정해지면
down_revision 또는 depends_on에 추가해서 순서를 강제할 것.

Revision ID: 0005_spots_external_fks
Revises: 0004_spots_updated_at_triggers
Create Date: 2026-04-27

체인 reorder: 외부 master 의존이 있는 이 마이그레이션을 마지막으로 미루고,
master 의존이 없는 트리거(0004)를 앞당겼다.
LDONG_CODES / LCLS_SYSTM_CODES / TAGS 마이그레이션이 들어오면 그때 적용.
"""
from __future__ import annotations

from alembic import op

revision = "0005_spots_external_fks"
down_revision = "0004_spots_updated_at_triggers"
branch_labels = None
# depends_on = ("xxxx_create_ldong_codes", "yyyy_create_lcls_systm", "zzzz_create_tags")
depends_on = None


def upgrade() -> None:
    # SPOTS_CORE.l_dong_regn_cd → LDONG_CODES.regn_cd
    op.execute("""
    ALTER TABLE spots_core
      ADD CONSTRAINT fk_spots_core_regn
      FOREIGN KEY (l_dong_regn_cd)
      REFERENCES ldong_codes(regn_cd)
      ON UPDATE CASCADE ON DELETE RESTRICT;
    """)

    # SPOTS_CORE.(regn_cd, signgu_cd) → LDONG_CODES 복합키
    op.execute("""
    ALTER TABLE spots_core
      ADD CONSTRAINT fk_spots_core_signgu
      FOREIGN KEY (l_dong_regn_cd, l_dong_signgu_cd)
      REFERENCES ldong_codes(regn_cd, signgu_cd)
      ON UPDATE CASCADE ON DELETE RESTRICT;
    """)

    # SPOTS_CORE.lcls_systm_1/2/3 → LCLS_SYSTM_CODES(code1, code2, code3)
    op.execute("""
    ALTER TABLE spots_core
      ADD CONSTRAINT fk_spots_core_lcls
      FOREIGN KEY (lcls_systm_1, lcls_systm_2, lcls_systm_3)
      REFERENCES lcls_systm_codes(code1, code2, code3)
      ON UPDATE CASCADE ON DELETE RESTRICT;
    """)

    # SPOT_TAGS.tag_id → TAGS.tag_id
    op.execute("""
    ALTER TABLE spot_tags
      ADD CONSTRAINT fk_spot_tags_tag
      FOREIGN KEY (tag_id)
      REFERENCES tags(tag_id)
      ON UPDATE CASCADE ON DELETE CASCADE;
    """)

    # SPOT_CONGESTION_FORECAST.signgu_cd → LDONG_CODES.signgu_cd
    # 주의: LDONG_CODES PK가 (regn_cd, signgu_cd) 복합이면 단독 signgu_cd FK는 못 건다.
    #       그 경우 area_cd를 regn_cd 매핑으로 같이 넣어 복합 FK로 변경 필요.
    #       master 마이그레이션 확정 후 실제 PK 형태에 맞춰 재조정.
    op.execute("""
    ALTER TABLE spot_congestion_forecast
      ADD CONSTRAINT fk_spot_congestion_signgu
      FOREIGN KEY (area_cd, signgu_cd)
      REFERENCES ldong_codes(regn_cd, signgu_cd)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE spot_congestion_forecast DROP CONSTRAINT IF EXISTS fk_spot_congestion_signgu;")
    op.execute("ALTER TABLE spot_tags DROP CONSTRAINT IF EXISTS fk_spot_tags_tag;")
    op.execute("ALTER TABLE spots_core DROP CONSTRAINT IF EXISTS fk_spots_core_lcls;")
    op.execute("ALTER TABLE spots_core DROP CONSTRAINT IF EXISTS fk_spots_core_signgu;")
    op.execute("ALTER TABLE spots_core DROP CONSTRAINT IF EXISTS fk_spots_core_regn;")
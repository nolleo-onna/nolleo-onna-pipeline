"""spots external FK attachments (after master tables land)

부착 대상:
- spots_core.(l_dong_regn_cd, l_dong_signgu_cd) → LDONG_CODES 복합키
- spots_core.lcls_systm_1/2/3                  → LCLS_SYSTM_CODES (복합키)
- spot_tags.tag_id                             → TAGS
- spot_congestion_forecast.(area_cd, signgu_cd) → LDONG_CODES

체인 부착 (2026-05-07):
- master 3종(LDONG/LCLS/TAGS)이 0006~0008로 적재됨에 따라 head에 합류.
- 0009_seed_master_codes_busan 가 부산 16 시군구 + 운영 데이터 백필을 끝낸 뒤
  본 FK 부착이 진행되어야 spots_core 기존 행 검증이 통과한다.

Revision ID: 0099_spots_external_fks
Revises: 0009_seed_master_codes_busan
Create Date: 2026-04-27 (reattach: 2026-05-07)
"""
from __future__ import annotations

from alembic import op

revision = "0099_spots_external_fks"
down_revision = "0009_seed_master_codes_busan"
branch_labels = None
depends_on = ("0006_create_ldong_codes", "0007_create_lcls_systm_codes")


def upgrade() -> None:
    # SPOTS_CORE.(l_dong_regn_cd, l_dong_signgu_cd) → LDONG_CODES 복합 PK
    # fk_spots_core_regn(단독) 제거: 복합 FK가 regn_cd를 이미 커버하며,
    # LDONG_CODES PK가 (regn_cd, signgu_cd) 복합이라 단독 참조 시 DDL 실패 가능.
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

    # SPOT_CONGESTION_FORECAST.(area_cd, signgu_cd) → LDONG_CODES(regn_cd, signgu_cd)
    # area_cd/signgu_cd 모두 NOT NULL이므로 ON DELETE RESTRICT.
    # SET NULL은 NOT NULL 제약과 충돌해 부모 삭제 시 런타임 오류 발생.
    op.execute("""
    ALTER TABLE spot_congestion_forecast
      ADD CONSTRAINT fk_spot_congestion_signgu
      FOREIGN KEY (area_cd, signgu_cd)
      REFERENCES ldong_codes(regn_cd, signgu_cd)
      ON UPDATE CASCADE ON DELETE RESTRICT;
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE spot_congestion_forecast "
        "DROP CONSTRAINT IF EXISTS fk_spot_congestion_signgu;"
    )
    op.execute("ALTER TABLE spot_tags DROP CONSTRAINT IF EXISTS fk_spot_tags_tag;")
    op.execute("ALTER TABLE spots_core DROP CONSTRAINT IF EXISTS fk_spots_core_lcls;")
    op.execute("ALTER TABLE spots_core DROP CONSTRAINT IF EXISTS fk_spots_core_signgu;")
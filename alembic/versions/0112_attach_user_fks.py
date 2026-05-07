"""attach deferred user FKs (sync_logs / bhr_queue / good_price_*)

operation.md §6 데이터 흐름 책임 매트릭스 / 각 도메인 #reviewed_by 등.

USERS 테이블이 0107로 적재된 후, 이전 마이그레이션에서 컬럼만 두고
미부착으로 남겨둔 user FK들을 일괄 부착.

부착 대상:
- sync_logs.triggered_by                      → users.id (수동 실행 admin)
- business_hours_review_queue.reviewed_by    → users.id (검수 admin)
- good_price_match_queue.reviewed_by          → users.id (검수 admin)
- good_price_price_observations.submitter_user_id → users.id (제보 user)
- good_price_price_observations.reviewed_by   → users.id (검수 admin)

ON DELETE 정책:
- triggered_by / reviewed_by : SET NULL (admin 탈퇴해도 이력 보존)
- submitter_user_id : SET NULL (탈퇴 사용자 제보 익명화 보존)

Revision ID: 0112_attach_user_fks
Revises: 0111_create_user_activity_tables
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0112_attach_user_fks"
down_revision = "0111_create_user_activity_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE sync_logs
      ADD CONSTRAINT fk_sync_logs_triggered_by
      FOREIGN KEY (triggered_by) REFERENCES users(id)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)

    op.execute("""
    ALTER TABLE business_hours_review_queue
      ADD CONSTRAINT fk_bhr_queue_reviewed_by
      FOREIGN KEY (reviewed_by) REFERENCES users(id)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)

    op.execute("""
    ALTER TABLE good_price_match_queue
      ADD CONSTRAINT fk_match_queue_reviewed_by
      FOREIGN KEY (reviewed_by) REFERENCES users(id)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)

    op.execute("""
    ALTER TABLE good_price_price_observations
      ADD CONSTRAINT fk_price_observations_submitter
      FOREIGN KEY (submitter_user_id) REFERENCES users(id)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)

    op.execute("""
    ALTER TABLE good_price_price_observations
      ADD CONSTRAINT fk_price_observations_reviewed_by
      FOREIGN KEY (reviewed_by) REFERENCES users(id)
      ON UPDATE CASCADE ON DELETE SET NULL;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE good_price_price_observations
      DROP CONSTRAINT IF EXISTS fk_price_observations_reviewed_by;
    """)
    op.execute("""
    ALTER TABLE good_price_price_observations
      DROP CONSTRAINT IF EXISTS fk_price_observations_submitter;
    """)
    op.execute("""
    ALTER TABLE good_price_match_queue
      DROP CONSTRAINT IF EXISTS fk_match_queue_reviewed_by;
    """)
    op.execute("""
    ALTER TABLE business_hours_review_queue
      DROP CONSTRAINT IF EXISTS fk_bhr_queue_reviewed_by;
    """)
    op.execute("""
    ALTER TABLE sync_logs
      DROP CONSTRAINT IF EXISTS fk_sync_logs_triggered_by;
    """)

"""create business_hours_review_queue (LLM 영업시간 검수 큐)

operation.md §3 콘텐츠 도메인 #BUSINESS_HOURS_REVIEW_QUEUE / ERD.

설계 포인트:
- LLM 할루시네이션 차단 파이프라인.
- 다층 검증: confidence + 룰 검증 + 원문 재구성 검증 → validation_passed.
- 추적성: model_name / model_version / prompt_version / source_text_hash.
- 임계값 3단계:
  - confidence ≥ 0.85 + validation_passed=true → 자동 적용 (큐 미진입)
  - 0.7 ~ 0.85 → 큐잉 + 24h SLA
  - < 0.7 또는 validation_passed=false → 큐잉 + UI "확인 필요"
- 처리 완료 row 30일 보관 후 hard delete.

reviewed_by → users 는 후속(0112)에서 부착.

Revision ID: 0106_create_bhr_queue
Revises: 0105_create_good_price_tables
Create Date: 2026-05-07

NOTE: revision id는 alembic_version.version_num VARCHAR(32) 제약 때문에 짧게 유지.
"""
from __future__ import annotations

from alembic import op

revision = "0106_create_bhr_queue"
down_revision = "0105_create_good_price_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE business_hours_review_queue (
        id                  BIGSERIAL   PRIMARY KEY,
        content_id          VARCHAR(20) NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        source_text         TEXT        NOT NULL,
        source_text_hash    VARCHAR(64) NOT NULL,
        parsed_json         JSONB,
        confidence          NUMERIC(4,3)
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        validation_passed   BOOLEAN     NOT NULL DEFAULT FALSE,
        model_name          VARCHAR(80) NOT NULL,
        model_version       VARCHAR(40) NOT NULL,
        prompt_version      VARCHAR(40) NOT NULL,
        reviewed_by         BIGINT,                       -- FK 후속 부착
        reviewed_at         TIMESTAMPTZ,
        review_status       VARCHAR(20) NOT NULL DEFAULT 'pending'
            CHECK (review_status IN ('pending','approved','rejected')),
        reviewer_note       TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # Q8: 검수 대기 화면 (관리자) — 오래된 것부터
    op.execute("""
    CREATE INDEX idx_bhr_queue_pending_created
        ON business_hours_review_queue (created_at)
        WHERE review_status = 'pending';
    """)

    # 동일 source_text 재큐잉 방지용 검색
    op.execute("""
    CREATE INDEX idx_bhr_queue_content_hash
        ON business_hours_review_queue (content_id, source_text_hash);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_bhr_queue_content_hash;")
    op.execute("DROP INDEX IF EXISTS idx_bhr_queue_pending_created;")
    op.execute("DROP TABLE IF EXISTS business_hours_review_queue;")

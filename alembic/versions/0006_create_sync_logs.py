"""create sync_logs for operations tracking

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.sync_logs (
        id              BIGSERIAL    PRIMARY KEY,
        job_name        VARCHAR(80)  NOT NULL,
        run_type        VARCHAR(20)  NOT NULL DEFAULT 'scheduled'
            CHECK (run_type IN ('scheduled', 'manual', 'triggered', 'regression')),
        status          VARCHAR(20)  NOT NULL DEFAULT 'running'
            CHECK (status IN ('running', 'success', 'failed', 'partial', 'cancelled')),
        triggered_by    BIGINT
            REFERENCES public.mb_user_info(id) ON DELETE SET NULL,
        parent_run_id   BIGINT
            REFERENCES public.sync_logs(id) ON DELETE SET NULL,
        started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        ended_at        TIMESTAMPTZ,
        duration_seconds INTEGER,
        api_calls_used   INTEGER,
        records_fetched  INTEGER,
        records_upserted INTEGER,
        records_failed   INTEGER,
        error_message    TEXT,
        metadata         JSONB       NOT NULL DEFAULT '{}'::jsonb
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.sync_logs IS '파이프라인 실행 이력/운영 로그';
    COMMENT ON COLUMN public.sync_logs.id IS '실행 로그 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.sync_logs.job_name IS '잡 이름';
    COMMENT ON COLUMN public.sync_logs.run_type IS '실행 타입(scheduled/manual/triggered/regression)';
    COMMENT ON COLUMN public.sync_logs.status IS '실행 상태(running/success/failed/partial/cancelled)';
    COMMENT ON COLUMN public.sync_logs.triggered_by IS '수동 실행 사용자 ID(FK)';
    COMMENT ON COLUMN public.sync_logs.parent_run_id IS '상위 실행 로그 ID(FK)';
    COMMENT ON COLUMN public.sync_logs.started_at IS '실행 시작 시각';
    COMMENT ON COLUMN public.sync_logs.ended_at IS '실행 종료 시각';
    COMMENT ON COLUMN public.sync_logs.duration_seconds IS '실행 시간(초)';
    COMMENT ON COLUMN public.sync_logs.api_calls_used IS '외부 API 호출 건수';
    COMMENT ON COLUMN public.sync_logs.records_fetched IS '조회 건수';
    COMMENT ON COLUMN public.sync_logs.records_upserted IS '반영 건수';
    COMMENT ON COLUMN public.sync_logs.records_failed IS '실패 건수';
    COMMENT ON COLUMN public.sync_logs.error_message IS '실패 메시지';
    COMMENT ON COLUMN public.sync_logs.metadata IS '잡별 확장 메타데이터(JSONB)';
    """)

    op.execute("""
    CREATE INDEX idx_sync_logs_job_started
        ON public.sync_logs (job_name, started_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_sync_logs_job_started;")
    op.execute("DROP TABLE IF EXISTS public.sync_logs;")

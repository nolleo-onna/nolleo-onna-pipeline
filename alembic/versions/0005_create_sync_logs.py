"""create sync_logs (운영 인프라)

operation.md §3 SYNC_LOGS:
- 모든 sync/cron/매칭/LLM/회귀 잡의 시작/종료/메트릭을 한 테이블에 통합 추적.
- common/sync_logs.py의 sync_log_run 컨텍스트가 이 테이블에 INSERT/UPDATE.

배치 결정:
- "운영 도메인" 라벨은 책임 분류일 뿐 배포 순서랑 무관.
- 모든 파이프라인(SPOTS, events, courses, ...)이 첫 줄에서 사용하는 인프라이므로
  외부 FK(0099)보다 앞 번호인 0005에 배치.

FK 처리:
- triggered_by → users : Spring 측 도메인이라 SPOTS 스코프 밖. 컬럼만 둠.
- parent_run_id → sync_logs(self) : 자기 참조라 즉시 인라인 부착.

Revision ID: 0005_create_sync_logs
Revises: 0004_spots_updated_at_triggers
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op

revision = "0005_create_sync_logs"
down_revision = "0004_spots_updated_at_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 본 테이블
    op.execute("""
    CREATE TABLE sync_logs (
        id                BIGSERIAL    PRIMARY KEY,

        -- 잡 식별
        job_name          VARCHAR(80)  NOT NULL,
        run_type          VARCHAR(20)  NOT NULL DEFAULT 'scheduled'
            CHECK (run_type IN ('scheduled','manual','triggered','regression')),
        status            VARCHAR(20)  NOT NULL DEFAULT 'running'
            CHECK (status IN ('running','success','failed','partial','cancelled')),

        -- 책임자/체인 추적
        -- triggered_by: 수동 실행 관리자. users 테이블 들어오면 후속에서 FK 부착.
        triggered_by      BIGINT,
        -- parent_run_id: 잡 chain (예: spots_sync → spots_embedding) 추적용. 자기 참조.
        parent_run_id     BIGINT
            REFERENCES sync_logs(id) ON DELETE SET NULL,

        -- 시각 (모두 TIMESTAMPTZ — operation.md §11)
        started_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        ended_at          TIMESTAMPTZ,                  -- running 중엔 NULL
        duration_seconds  INTEGER,                      -- ended_at 시점에 계산해 박음

        -- 메트릭
        api_calls_used    INTEGER      NOT NULL DEFAULT 0,
        records_fetched   INTEGER      NOT NULL DEFAULT 0,
        records_upserted  INTEGER      NOT NULL DEFAULT 0,
        records_failed    INTEGER      NOT NULL DEFAULT 0,

        -- 진단
        error_message     TEXT,                         -- failed/partial 시 사유
        metadata          JSONB                         -- 잡별 상세 (모델명, 페이지수 등)
    );
    """)

    # 2) 인덱스 — 운영 화면/모니터링 핫패스
    # (a) "최근 잡 X의 실행 이력" — job_name + 시간 역순
    op.execute("""
    CREATE INDEX idx_sync_logs_job_name_started
        ON sync_logs (job_name, started_at DESC);
    """)

    # (b) 실패/실행중 모니터링 — partial 인덱스로 가볍게
    op.execute("""
    CREATE INDEX idx_sync_logs_status_running_failed
        ON sync_logs (started_at DESC)
        WHERE status IN ('running', 'failed');
    """)

    # 3) updated_at 트리거 미부착:
    #    sync_logs는 row 갱신 자체가 sync_log_run 컨텍스트에서만 일어나고,
    #    ended_at/status 변경이 그 자체로 갱신 시각 역할을 한다.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sync_logs;")
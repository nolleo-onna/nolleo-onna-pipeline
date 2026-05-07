"""SYNC_LOGS 적재 헬퍼.

[이 파일이 왜 있냐]
operation.md §3 SYNC_LOGS: 모든 sync/cron/매칭/LLM 잡의 시작·종료·메트릭을 한 테이블에 기록.
"이 잡 언제 돌렸나, 몇 건 처리했나, 실패는 뭐였나" 단일 진실 원천.

이 파일이 제공하는 것: `async with sync_log_run(...)` 블록 안에서 자동으로
- 시작 시 status='running' 행 INSERT
- 정상 종료 시 status='success' + 메트릭 UPDATE
- 예외 시 status='failed' + error_message UPDATE
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.common.timezone import now_utc


@dataclass
class SyncLogContext:
    """잡 실행 동안 메트릭을 누적하는 그릇.

    파이프라인 코드가 ctx.records_fetched += 1 식으로 직접 카운팅.
    블록 끝나면 자동으로 DB에 반영.
    """
    job_name: str
    run_type: str = "scheduled"   # 'scheduled' | 'manual' | 'triggered' | 'regression'
    api_calls_used: int = 0
    records_fetched: int = 0
    records_upserted: int = 0
    records_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    # 내부용 — INSERT 후 받아오는 PK
    row_id: int | None = None


@asynccontextmanager
async def sync_log_run(
    job_name: str,
    run_type: str = "scheduled",
) -> AsyncIterator[SyncLogContext]:
    """SYNC_LOGS 행을 자동으로 시작/종료 관리하는 컨텍스트 매니저.

    사용법:
        async with sync_log_run("tourapi_spots_sync") as ctx:
            ...실제 작업...
            ctx.records_fetched += 1
        # 블록 끝나면 자동으로 status='success'로 마감

        예외 발생 시 → status='failed' + error_message 기록 후 예외 재발생.
    """
    ctx = SyncLogContext(job_name=job_name, run_type=run_type)
    pool = await get_pool()

    # 1) 시작 행 INSERT
    async with pool.connection() as conn, conn.transaction():
        row = await conn.execute(
            """
            INSERT INTO sync_logs (job_name, run_type, status, started_at)
            VALUES (%s, %s, 'running', %s)
            RETURNING id
            """,
            (ctx.job_name, ctx.run_type, now_utc()),
        )
        result = await row.fetchone()
        if result is not None:
            ctx.row_id = cast(dict[str, Any], result)["id"]

    # 2) 본 작업 실행 (with 블록)
    try:
        yield ctx                                 # 호출자에게 ctx 넘김
    except Exception as exc:
        # 3a) 실패 — 에러 기록 후 예외 재발생
        await _finalize(ctx, status="failed", error_message=str(exc))
        raise
    else:
        # 3b) 성공 — 메트릭 마감
        await _finalize(ctx, status="success", error_message=None)


async def _finalize(
    ctx: SyncLogContext,
    *,
    status: str,
    error_message: str | None,
) -> None:
    """블록 종료 시 SYNC_LOGS 행 UPDATE."""
    if ctx.row_id is None:
        return
    pool = await get_pool()
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            """
            UPDATE sync_logs
               SET status = %s,
                   ended_at = %s,
                   duration_seconds =
                       EXTRACT(EPOCH FROM (%s - started_at))::int,
                   api_calls_used = %s,
                   records_fetched = %s,
                   records_upserted = %s,
                   records_failed = %s,
                   error_message = %s,
                   metadata = %s::jsonb
             WHERE id = %s
            """,
            (
                status,
                now_utc(),
                now_utc(),
                ctx.api_calls_used,
                ctx.records_fetched,
                ctx.records_upserted,
                ctx.records_failed,
                error_message,
                json.dumps(ctx.metadata, ensure_ascii=False),
                ctx.row_id,
            ),
        )

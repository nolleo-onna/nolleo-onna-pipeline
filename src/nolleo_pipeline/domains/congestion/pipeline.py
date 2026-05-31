"""Congestion 도메인 sync 오케스트레이션.

[이 파일이 왜 있냐]
- 3개 잡:
    · tourapi_congestion_sync          : 부산 시군구 16개 × 30일치 적재
    · today_concentration_cache_refresh: SPOTS 캐시 3컬럼 갱신 (4중 가드)
    · congestion_old_purge             : 7일 이전 base_ymd row cleanup
- ADR 0003 4중 가드 패턴 재사용으로 부분 적재 직후 캐시 갱신 차단.

[흐름]
시군구 루프 → 페이지 호출 → 매칭 → batch upsert → ctx 카운트
                                                        ↓
                                                  SYNC_LOGS 마감
                                                        ↓
[다음 cron] 캐시 갱신 잡이 직전 sync metadata 보고 가드 4종 평가
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, cast

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.common.http import build_http_client
from nolleo_pipeline.common.sync_logs import SyncLogContext, sync_log_run
from nolleo_pipeline.common.timezone import now_kst, now_utc
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.congestion.client import TourApiCongestionClient
from nolleo_pipeline.domains.congestion.models import CongestionForecastRecord
from nolleo_pipeline.domains.congestion.parser import parse_congestion_response
from nolleo_pipeline.domains.congestion.repository import CongestionRepository

# 부산 areaCd (operation.md §3 LDONG_CODES "부산 16개 시군구 시드")
BUSAN_AREA_CD = "26"
DEFAULT_NUM_OF_ROWS = 100

# 잡 이름 (operation.md §3 SYNC_LOGS job_name 규약)
JOB_SYNC = "tourapi_congestion_sync"
JOB_CACHE = "today_concentration_cache_refresh"
JOB_PURGE = "congestion_old_purge"

# operation.md §3 SPOT_CONGESTION_FORECAST: "30일 예측 + 7일 과거 보관"
PURGE_RETENTION_DAYS = 7


# ─── 잡 1: tourapi_congestion_sync ───────────────────────────────

async def run_tourapi_congestion_sync(
    *,
    area_cd: str = BUSAN_AREA_CD,
    num_of_rows: int = DEFAULT_NUM_OF_ROWS,
) -> None:
    """TourAPI 혼잡도 예측 일일 sync.

    부산 시군구 16개 × 페이지 돌기 → 매칭 → upsert.
    매뉴얼 v4.0: 한 호출에 그 시군구의 모든 관광지 × 30일치가 응답으로 옴.
    """
    settings = get_settings()
    repo = CongestionRepository()
    api_budget_limit = settings.daily_api_call_limit

    async with sync_log_run(JOB_SYNC) as ctx:
        # ADR 0003 호환 가드용 metadata + 자체 metric 초기화
        ctx.metadata.setdefault("area_cd", area_cd)
        ctx.metadata.setdefault("api_budget_limit", api_budget_limit)
        ctx.metadata.setdefault("stopped_by_budget", False)
        ctx.metadata.setdefault("bootstrap_complete", False)
        ctx.metadata.setdefault("signgus_completed", 0)
        ctx.metadata.setdefault("signgus_total", 0)
        ctx.metadata.setdefault("null_content_id_count", 0)
        ctx.metadata.setdefault("match_rate", None)
        ctx.metadata.setdefault("null_ratio", None)
        ctx.metadata.setdefault("failure_rate", None)

        signgu_codes = await repo.list_signgu_codes_by_area(area_cd)
        ctx.metadata["signgus_total"] = len(signgu_codes)

        async with build_http_client() as http:
            client = TourApiCongestionClient(
                http, service_key=settings.tour_api_key
            )

            for area, signgu in signgu_codes:
                if ctx.api_calls_used >= api_budget_limit:
                    ctx.metadata["stopped_by_budget"] = True
                    break
                try:
                    await _sync_one_signgu(
                        client=client,
                        repo=repo,
                        ctx=ctx,
                        area_cd=area,
                        signgu_cd=signgu,
                        num_of_rows=num_of_rows,
                        api_budget_limit=api_budget_limit,
                    )
                    ctx.metadata["signgus_completed"] += 1
                except Exception as exc:                          # noqa: BLE001
                    # per-시군구 실패는 잡 전체 실패로 안 만듦, 메트릭에만
                    ctx.records_failed += 1
                    ctx.metadata.setdefault("errors", []).append(
                        {"signgu_cd": signgu, "error": str(exc)[:300]}
                    )

        # 회차 종료 — 가드용 derived metric 계산
        ctx.metadata["bootstrap_complete"] = (
            ctx.metadata["signgus_completed"] == ctx.metadata["signgus_total"]
            and not ctx.metadata["stopped_by_budget"]
        )
        upserted_denom = max(ctx.records_upserted, 1)
        fetched_denom = max(ctx.records_fetched, 1)
        null_count = int(ctx.metadata["null_content_id_count"])
        ctx.metadata["null_ratio"] = null_count / upserted_denom
        ctx.metadata["match_rate"] = (
            (ctx.records_upserted - null_count) / upserted_denom
        )
        ctx.metadata["failure_rate"] = ctx.records_failed / fetched_denom


async def _sync_one_signgu(
    *,
    client: TourApiCongestionClient,
    repo: CongestionRepository,
    ctx: SyncLogContext,
    area_cd: str,
    signgu_cd: str,
    num_of_rows: int,
    api_budget_limit: int,
) -> None:
    """단일 시군구 — 페이지 끝까지 호출 후 매칭 + batch upsert."""
    # TourAPI signguCd는 area_cd + signgu_cd 결합 5자리 형식(예: 26 + 110 = 26110).
    # 내부 표준(LDONG_CODES/SPOTS)은 3자리 signgu_cd를 유지하고,
    # API 호출 시점에서만 결합 코드를 사용한다.
    api_signgu_cd = f"{area_cd}{signgu_cd}"
    page = 1
    fetched_at = now_utc()
    all_records: list[CongestionForecastRecord] = []

    while True:
        if ctx.api_calls_used >= api_budget_limit:
            ctx.metadata["stopped_by_budget"] = True
            break

        ctx.api_calls_used += 1
        payload = await client.list_by_signgu(
            area_cd=area_cd,
            signgu_cd=api_signgu_cd,
            page=page,
            num_of_rows=num_of_rows,
        )
        records = parse_congestion_response(payload, fetched_at=fetched_at)
        if not records:
            break

        ctx.records_fetched += len(records)
        all_records.extend(records)

        # 매뉴얼 페이지네이션: 응답이 num_of_rows보다 적으면 마지막 페이지
        if len(records) < num_of_rows:
            break
        page += 1

    if not all_records:
        return

    # 매칭 — 시군구당 unique raw_tats_name만 SELECT해서 중복 호출 회피
    match_cache: dict[str, str | None] = {}
    unique_names = {record.raw_tats_name for record in all_records}
    for name in unique_names:
        try:
            match_cache[name] = await repo.match_by_raw_name_in_signgu(
                raw_tats_name=name,
                signgu_cd=signgu_cd,
            )
        except Exception as exc:                                  # noqa: BLE001
            # 매칭 실패는 unmatched로 적재하고 계속 — 잡 전체 실패 안 만듦
            ctx.metadata.setdefault("errors", []).append(
                {
                    "raw_tats_name": name,
                    "stage": "match",
                    "error": str(exc)[:200],
                }
            )
            match_cache[name] = None

    # 캐시된 매칭 결과를 record별로 반영
    for record in all_records:
        content_id = match_cache.get(record.raw_tats_name)
        record.content_id = content_id
        if content_id is None:
            ctx.metadata["null_content_id_count"] += 1

    # batch upsert (matched/unmatched 자동 분리, partial UK 정확 일치)
    matched_count, unmatched_count = await repo.upsert_forecasts(all_records)
    ctx.records_upserted += matched_count + unmatched_count


# ─── 잡 2: today_concentration_cache_refresh ─────────────────────

async def run_today_concentration_cache_refresh() -> None:
    """SPOTS 혼잡도 캐시 3컬럼 갱신 (sync 직후 cron).

    ADR 0003 4중 가드 패턴 재사용 — 직전 `tourapi_congestion_sync`
    metadata 보고 부분 적재 회차면 skip.
    """
    settings = get_settings()
    repo = CongestionRepository()

    async with sync_log_run(JOB_CACHE) as ctx:
        ctx.metadata.setdefault("cache_skipped", None)
        ctx.metadata.setdefault("cache_skip_reason", None)
        ctx.metadata.setdefault("cache_updated_count", 0)
        ctx.metadata.setdefault("referenced_sync_log_id", None)

        await _refresh_cache_if_safe(
            repo=repo,
            ctx=ctx,
            max_failure_rate=settings.spots_deactivate_max_failure_rate,
            max_null_ratio=settings.spots_congestion_max_null_ratio,
        )


async def _refresh_cache_if_safe(
    *,
    repo: CongestionRepository,
    ctx: SyncLogContext,
    max_failure_rate: float,
    max_null_ratio: float,
) -> None:
    """ADR 0003 4중 가드 평가 후 통과 시에만 캐시 SQL 실행.

    가드:
        1. bootstrap_complete=True
        2. stopped_by_budget=False
        3. failure_rate < max_failure_rate
        4. null_ratio < max_null_ratio (혼잡도 도메인 고유)

    가드 통과 후의 SQL 실패는 try/except로 흡수 — 캐시 갱신 실패는
    sync 잡 'success'를 가리지 않음 (ADR 0003 §4).
    """
    try:
        prev = await _load_previous_sync_metadata(JOB_SYNC)
        if prev is None:
            ctx.metadata["cache_skipped"] = True
            ctx.metadata["cache_skip_reason"] = "no_previous_sync"
            return

        sync_id, sync_meta, fetched, upserted, failed = prev
        ctx.metadata["referenced_sync_log_id"] = sync_id

        # 가드 1
        if not sync_meta.get("bootstrap_complete", False):
            ctx.metadata["cache_skipped"] = True
            ctx.metadata["cache_skip_reason"] = "partial_sync"
            return

        # 가드 2
        if sync_meta.get("stopped_by_budget", False):
            ctx.metadata["cache_skipped"] = True
            ctx.metadata["cache_skip_reason"] = "stopped_by_budget"
            return

        # 가드 3
        failure_rate = failed / max(fetched, 1)
        if failure_rate >= max_failure_rate:
            ctx.metadata["cache_skipped"] = True
            ctx.metadata["cache_skip_reason"] = "high_failure_rate"
            return

        # 가드 4
        null_count = int(sync_meta.get("null_content_id_count", 0))
        null_ratio = null_count / max(upserted, 1)
        if null_ratio >= max_null_ratio:
            ctx.metadata["cache_skipped"] = True
            ctx.metadata["cache_skip_reason"] = "high_null_ratio"
            return

        # 모든 가드 통과 — 캐시 SQL 실행
        today = now_kst().date()
        updated = await repo.refresh_today_concentration_cache(
            today=today,
            updated_at=now_utc(),
        )
        ctx.metadata["cache_skipped"] = False
        ctx.metadata["cache_skip_reason"] = None
        ctx.metadata["cache_updated_count"] = updated
    except Exception as exc:                                      # noqa: BLE001
        ctx.metadata["cache_skipped"] = True
        ctx.metadata["cache_skip_reason"] = "exception"
        ctx.metadata.setdefault("errors", []).append(
            {"stage": "cache_refresh", "error": str(exc)[:300]}
        )


# ─── 잡 3: congestion_old_purge ──────────────────────────────────

async def run_congestion_old_purge() -> None:
    """7일 이전 base_ymd row 일괄 삭제.

    operation.md §3 SPOT_CONGESTION_FORECAST: "30일 예측 + 7일 과거 보관".
    단순 cleanup — 안전 가드 불필요.
    """
    repo = CongestionRepository()
    cutoff = now_kst().date() - timedelta(days=PURGE_RETENTION_DAYS)

    async with sync_log_run(JOB_PURGE) as ctx:
        ctx.metadata["cutoff_date"] = cutoff.isoformat()
        purged = await repo.purge_old_forecasts(cutoff_date=cutoff)
        ctx.metadata["purged_count"] = purged


# ─── 헬퍼: 직전 sync 잡 metadata 로드 ────────────────────────────

async def _load_previous_sync_metadata(
    job_name: str,
) -> tuple[int, dict[str, Any], int, int, int] | None:
    """직전 status='success' 잡의 (id, metadata, fetched, upserted, failed) 조회.

    Returns:
        None: 이전 success 회차가 없음 (콜드 스타트).
        tuple: 가드 평가에 필요한 5개 필드.
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await conn.execute(
            """
            SELECT id, metadata,
                   records_fetched, records_upserted, records_failed
              FROM sync_logs
             WHERE job_name = %s
               AND status   = 'success'
             ORDER BY id DESC
             LIMIT 1
            """,
            (job_name,),
        )
        result = await row.fetchone()
        if result is None:
            return None
        record = cast(dict[str, Any], result)

        meta_raw = record.get("metadata")
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw)
            except json.JSONDecodeError:
                meta = {}
        elif isinstance(meta_raw, dict):
            meta = meta_raw
        else:
            meta = {}

        return (
            int(record["id"]),
            meta,
            int(record["records_fetched"] or 0),
            int(record["records_upserted"] or 0),
            int(record["records_failed"] or 0),
        )

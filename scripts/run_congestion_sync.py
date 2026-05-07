# scripts/run_congestion_sync.py
"""부산 혼잡도 sync + 캐시 + cleanup 1회 수동 실행 (smoke test용).

흐름:
  1. tourapi_congestion_sync          — 부산 시군구 16개 × 30일치 적재
  2. today_concentration_cache_refresh — SPOTS_CORE 캐시 3컬럼 갱신 (4중 가드)
  3. congestion_old_purge             — 7일 이전 row cleanup

실행 후 결과 확인:
    psql ... -c "
    SELECT id, job_name, status, records_fetched, records_upserted, records_failed,
           duration_seconds, metadata
      FROM sync_logs
     WHERE job_name IN (
        'tourapi_congestion_sync',
        'today_concentration_cache_refresh',
        'congestion_old_purge'
     )
     ORDER BY id DESC LIMIT 10;
    "

주의: 개발계정 일 1,000건 한도. 부산 16개 시군구는 ~80~240건 사용 예상.
"""
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.congestion.pipeline import (
    run_congestion_old_purge,
    run_today_concentration_cache_refresh,
    run_tourapi_congestion_sync,
)


async def main() -> None:
    try:
        print("=== [1/3] tourapi_congestion_sync 시작 ===")
        await run_tourapi_congestion_sync()
        print("=== [2/3] today_concentration_cache_refresh 시작 ===")
        await run_today_concentration_cache_refresh()
        print("=== [3/3] congestion_old_purge 시작 ===")
        await run_congestion_old_purge()
        print("=== 완료 — SYNC_LOGS 확인 권장 ===")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

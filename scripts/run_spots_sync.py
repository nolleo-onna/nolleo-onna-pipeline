# scripts/run_spots_sync.py
"""부산 관광지 sync 1회 수동 실행 (smoke test용)."""
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.spots.pipeline import run_tourapi_spots_sync


async def main() -> None:
    try:
        # 처음엔 max_pages=1로 시험 — 페이지 1개(=100건)만 돌려보고 멈춤.
        await run_tourapi_spots_sync(max_pages=None, num_of_rows=100)
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
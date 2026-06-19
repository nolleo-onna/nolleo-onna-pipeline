"""fd_food_places 주소 → 좌표 지오코딩 보강."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.geocoding.pipeline import run_food_place_geocode_sync


async def main() -> None:
    parser = argparse.ArgumentParser(description="Geocode fd_food_places addresses via Kakao Local API")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 호출과 좌표 계산만 하고 fd_food_places는 갱신하지 않음",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 음식 장소 수 상한",
    )
    args = parser.parse_args()

    try:
        result = await run_food_place_geocode_sync(
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(
            "food place geocode: "
            f"places_scanned={result.places_scanned}, "
            f"geocoded={result.geocoded_count}, "
            f"failed={result.failed_count}, "
            f"skipped_no_address={result.skipped_no_address}, "
            f"dry_run={result.dry_run}"
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

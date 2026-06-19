"""fd_food_places ↔ spots 룰 매칭 → fd_food_place_spot_matches 적재."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.good_price.matcher import MAX_CANDIDATE_DISTANCE_M
from nolleo_pipeline.domains.good_price.pipeline import run_food_spot_match_sync


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match fd_food_places to TourAPI food spots into fd_food_place_spot_matches",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="매칭 결과만 계산하고 fd_food_place_spot_matches는 갱신하지 않음",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 음식 장소 수 상한",
    )
    parser.add_argument(
        "--rematch-pending",
        action="store_true",
        help="기존 rule pending 매칭도 다시 계산",
    )
    parser.add_argument(
        "--max-distance-m",
        type=float,
        default=MAX_CANDIDATE_DISTANCE_M,
        help="스팟 후보 검색 반경(미터)",
    )
    args = parser.parse_args()

    try:
        result = await run_food_spot_match_sync(
            dry_run=args.dry_run,
            limit=args.limit,
            rematch_pending=args.rematch_pending,
            max_distance_m=args.max_distance_m,
        )
        print(
            "food spot match: "
            f"places_scanned={result.places_scanned}, "
            f"upserted={result.matches_upserted}, "
            f"matched={result.matched_count}, "
            f"pending={result.pending_count}, "
            f"separate={result.separate_count}, "
            f"no_candidate={result.no_candidate_count}, "
            f"dry_run={result.dry_run}"
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

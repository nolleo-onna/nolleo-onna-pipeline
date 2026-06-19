"""fd_food_* 현재 메뉴 가격 → sp_spot_price_summary 갱신."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.good_price.pipeline import refresh_spot_price_summary


async def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh spot price summaries from fd_food_*")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="집계 대상 수만 계산하고 sp_spot_price_summary는 갱신하지 않음",
    )
    parser.add_argument(
        "--prune-missing",
        action="store_true",
        help="이번 집계 대상에 없는 sp_spot_price_summary row 삭제",
    )
    args = parser.parse_args()

    try:
        result = await refresh_spot_price_summary(
            dry_run=args.dry_run,
            prune_missing=args.prune_missing,
        )
        print(
            "spot price summary refresh: "
            f"aggregated={result.aggregated_count}, "
            f"upserted={result.upserted_count}, "
            f"pruned={result.pruned_count}, "
            f"dry_run={result.dry_run}"
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

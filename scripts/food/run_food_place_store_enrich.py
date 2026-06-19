"""good_price_store → good_price_menu 주소·좌표·연락처 병합."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.good_price.pipeline import run_food_place_store_enrich_sync


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich good_price_menu places from matching good_price_store rows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="병합 대상만 집계하고 fd_food_places는 갱신하지 않음",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 메뉴 장소 수 상한",
    )
    args = parser.parse_args()

    try:
        result = await run_food_place_store_enrich_sync(
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(
            "food place store enrich: "
            f"menu_scanned={result.menu_places_scanned}, "
            f"store_matches={result.store_name_matches}, "
            f"enriched={result.enriched_count}, "
            f"address_filled={result.address_filled}, "
            f"coords_filled={result.coords_filled}, "
            f"tel_filled={result.tel_filled}, "
            f"no_store_match={result.no_store_match}, "
            f"dry_run={result.dry_run}"
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

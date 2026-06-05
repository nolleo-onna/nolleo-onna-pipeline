"""부산 착한가격업소 메뉴 API → food_* 테이블 적재."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.good_price.pipeline import run_good_price_menu_api_sync


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Busan good-price menus into food_*")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--num-of-rows", type=int, default=100)
    args = parser.parse_args()
    try:
        await run_good_price_menu_api_sync(
            max_pages=args.max_pages,
            num_of_rows=args.num_of_rows,
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

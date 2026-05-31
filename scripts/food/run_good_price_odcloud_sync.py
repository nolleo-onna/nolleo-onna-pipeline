"""odcloud 착한가격업소 데이터셋 API → food_* 테이블 적재."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.good_price.pipeline import run_good_price_odcloud_sync


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync odcloud good-price dataset into food_*")
    parser.add_argument("--endpoint-url", required=True, help="odcloud dataset API endpoint URL")
    parser.add_argument("--source-name", required=True, help="human-readable source label")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--per-page", type=int, default=100)
    args = parser.parse_args()
    try:
        await run_good_price_odcloud_sync(
            endpoint_url=args.endpoint_url,
            source_name=args.source_name,
            max_pages=args.max_pages,
            per_page=args.per_page,
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

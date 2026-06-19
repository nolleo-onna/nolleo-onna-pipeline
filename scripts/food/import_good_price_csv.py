"""착한가격업소 CSV/파일 → fd_food_* 테이블 적재."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.good_price.pipeline import import_good_price_file


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import good-price CSV into fd_food_*")
    parser.add_argument("path", help="CSV file path")
    args = parser.parse_args()
    try:
        await import_good_price_file(args.path)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

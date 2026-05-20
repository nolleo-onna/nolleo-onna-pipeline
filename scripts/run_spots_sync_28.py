# scripts/run_spots_sync_28.py
"""부산(26) 레포츠(contentTypeId=28)만 TourAPI sync — 수동 1회."""
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.spots.pipeline import run_tourapi_spots_sync


async def main() -> None:
    try:
        await run_tourapi_spots_sync(
            l_dong_regn_cd="26",
            content_type_ids=("28",),
            max_pages=None,
            num_of_rows=100,
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
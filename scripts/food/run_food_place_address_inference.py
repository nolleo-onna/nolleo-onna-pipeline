"""주소 없는 fd_food_places → Kakao 키워드 + LLM 주소 추론 → 좌표 보강."""
from __future__ import annotations

import argparse
import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.geocoding.pipeline import run_food_place_address_inference_sync


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infer missing fd_food_places address/coordinates via Kakao keyword and LLM",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="추론만 수행하고 fd_food_places는 갱신하지 않음",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 음식 장소 수 상한",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Kakao 키워드 검색만 사용하고 LLM 주소 추론은 건너뜀",
    )
    args = parser.parse_args()

    try:
        result = await run_food_place_address_inference_sync(
            dry_run=args.dry_run,
            limit=args.limit,
            skip_llm=args.skip_llm,
        )
        print(
            "food place address inference: "
            f"places_scanned={result.places_scanned}, "
            f"resolved={result.resolved_count}, "
            f"keyword={result.keyword_resolved_count}, "
            f"llm={result.llm_resolved_count}, "
            f"failed={result.failed_count}, "
            f"skipped_low_confidence={result.skipped_low_confidence}, "
            f"dry_run={result.dry_run}"
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

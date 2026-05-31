"""부산(법정동 시도 26) 여행코스(ContentTypeId=25) 전량 sync — 수동 1회 실행."""

import asyncio

from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.travel_courses.pipeline import (
    run_tourapi_travel_courses_sync,
)


async def main() -> None:
    try:
        await run_tourapi_travel_courses_sync(
            l_dong_regn_cd="26",  # 부산
            max_pages=None,       # 전체 페이지
            num_of_rows=100,      # TourAPI 권장 최대치
        )
    finally:
        # 커넥션 풀 정리 (스크립트 종료 시 누수 방지)
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
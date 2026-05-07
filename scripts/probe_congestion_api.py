# scripts/probe_congestion_api.py
"""TourAPI 혼잡도 응답을 시군구 1개로 호출만 해서 출력 (DB 적재 X).

용도:
- 첫 실 적재 전 API 키/네트워크/응답 형식 검증.
- run_congestion_sync.py 돌리기 전 안전장치.

사용:
    python scripts/probe_congestion_api.py

출력:
    1) TourAPI 원본 응답 JSON (header + body)
    2) parse_congestion_response 결과 5개 (level 파생 확인용)

API 호출 횟수: 1건 (개발계정 한도에 거의 영향 X).
"""
import asyncio
import json

from nolleo_pipeline.common.http import build_http_client
from nolleo_pipeline.common.timezone import now_utc
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.congestion.client import TourApiCongestionClient
from nolleo_pipeline.domains.congestion.parser import parse_congestion_response

# 시험용 — 부산 중구 (LDONG 신체계: 26 = 부산, 26110 = 중구)
PROBE_AREA_CD = "26"
PROBE_SIGNGU_CD = "26110"
PROBE_NUM_OF_ROWS = 10


async def main() -> None:
    settings = get_settings()
    async with build_http_client() as http:
        client = TourApiCongestionClient(http, service_key=settings.tour_api_key)
        payload = await client.list_by_signgu(
            area_cd=PROBE_AREA_CD,
            signgu_cd=PROBE_SIGNGU_CD,
            page=1,
            num_of_rows=PROBE_NUM_OF_ROWS,
        )

        print("=== 원본 응답 (header + body) ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print()

        records = parse_congestion_response(payload, fetched_at=now_utc())
        print(f"=== 파싱 결과 — 총 {len(records)}개 record (처음 5개만 출력) ===")
        for record in records[:5]:
            print(record.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

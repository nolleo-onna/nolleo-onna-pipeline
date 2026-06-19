"""Travel Courses 도메인 동기화 오케스트레이션.

[이 파일이 왜 있냐]
- client + parser + repository를 묶어 "코스 동기화 잡 1회 실행 흐름"을 구성한다.
- sync_logs에 시작/종료/메트릭/실패를 일관 기록한다.
- 코스 단위 예외 격리(per-course try/except)로 전체 잡 중단을 방지한다.

[흐름]
list(contentTypeId=25) -> fetch_full -> parse -> upsert/replace -> sync_log finalize
"""

from __future__ import annotations

from typing import Any

from nolleo_pipeline.common.http import build_http_client
from nolleo_pipeline.common.sync_logs import sync_log_run
from nolleo_pipeline.common.timezone import now_utc
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.travel_courses.client import TourApiTravelCourseClient
from nolleo_pipeline.domains.travel_courses.parser import parse_course
from nolleo_pipeline.domains.travel_courses.repository import TravelCoursesRepository

DEFAULT_BUSAN_REGN_CD = "26"


async def run_tourapi_travel_courses_sync(
    *,
    l_dong_regn_cd: str = DEFAULT_BUSAN_REGN_CD,
    num_of_rows: int = 100,
    max_pages: int | None = None,
    run_type: str = "manual",
) -> None:
    """TourAPI 여행코스(contentTypeId=25) 동기화 진입점.

    run_type: sync_logs.run_type. 하네스(run_job)가 실행 맥락(manual/scheduled)에
              맞춰 주입한다. 직접 호출 시 기본 "manual".
    """
    settings = get_settings()
    repo = TravelCoursesRepository()

    async with sync_log_run("tourapi_courses_sync", run_type=run_type) as ctx:
        async with build_http_client() as http:
            client = TourApiTravelCourseClient(http, service_key=settings.tour_api_key)

            page = 1
            while True:
                if max_pages is not None and page > max_pages:
                    break

                list_payload = await client.list(
                    l_dong_regn_cd=l_dong_regn_cd,
                    page=page,
                    num_of_rows=num_of_rows,
                )
                ctx.api_calls_used += 1

                items = _extract_list_items(list_payload)
                if not items:
                    break

                for item in items:
                    content_id = _extract_content_id(item)
                    if not content_id:
                        ctx.records_failed += 1
                        continue

                    try:
                        endpoints = await client.fetch_full(content_id=content_id, content_type_id="25")
                        ctx.api_calls_used += 4
                        fetched_at = now_utc()
                        parsed = parse_course(
                            endpoints,
                            synced_at=fetched_at,
                            fetched_at=fetched_at,
                        )
                        await repo.upsert_course(parsed)
                        ctx.records_upserted += 1
                    except Exception as exc:
                        ctx.records_failed += 1
                        errors = ctx.metadata.setdefault("errors", [])
                        if isinstance(errors, list) and len(errors) < 50:
                            errors.append({"content_id": content_id, "error": str(exc)[:300]})

                    ctx.records_fetched += 1

                ctx.metadata["current_page"] = page
                page += 1


def _extract_list_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items")
    if not isinstance(items, dict):
        return []
    item = items.get("item")
    if isinstance(item, list):
        return [i for i in item if isinstance(i, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def _extract_content_id(item: dict[str, Any]) -> str | None:
    value = item.get("contentid")
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return text or None
    return None
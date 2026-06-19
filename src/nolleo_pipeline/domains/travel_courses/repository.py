"""Travel Courses 도메인 DB I/O.

[이 파일이 왜 있냐]
- ParsedTravelCourse를 실제 DB 테이블에 분배 저장하는 계층.
- operation.md의 저장 정책을 트랜잭션으로 강제한다.
  - TRAVEL_COURSES: UPSERT
  - TRAVEL_COURSE_RAW_SNAPSHOTS: UPSERT
  - COURSE_ITEMS: REPLACE(DELETE + INSERT)

[핵심 규약]
- COURSE_ITEMS는 반드시 단일 트랜잭션에서 DELETE+INSERT 수행.
- 한 코스 저장 중 하나라도 실패하면 전체 롤백.
"""

from __future__ import annotations

from typing import Any, cast

from psycopg import AsyncConnection
from psycopg.types.json import Json

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.domains.travel_courses.models import (
    CourseItemRecord,
    CourseRawSnapshot,
    ParsedTravelCourse,
    TravelCourseRecord,
)

# 접두사 컨벤션(tv_/sp_) 적용된 실제 테이블명. RDS 스키마/alembic과 정합.
TRAVEL_COURSES_TABLE = "tv_travel_courses"
TRAVEL_COURSE_RAW_SNAPSHOTS_TABLE = "tv_travel_course_raw_snapshots"
COURSE_ITEMS_TABLE = "tv_course_items"
SPOTS_TABLE = "sp_spots"


class TravelCoursesRepository:
    """파이프라인에서 호출하는 DB 저장 진입점."""

    async def upsert_course(self, parsed: ParsedTravelCourse) -> None:
        """한 코스 단위로 core/raw/items를 단일 트랜잭션 저장."""
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            await self._upsert_travel_course(conn, parsed.course)
            await self._upsert_raw_snapshot(conn, parsed.raw)
            await self._replace_course_items(conn, parsed.course.content_id, parsed.items)

    async def _upsert_travel_course(
        self,
        conn: AsyncConnection,
        course: TravelCourseRecord,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {TRAVEL_COURSES_TABLE} (
                content_id, title, overview, overview_hash, theme,
                taketime, taketime_minutes, distance, distance_km,
                schedule, infocenter_tourcourse, first_image, first_image_cpyrht_div_cd,
                l_dong_regn_cd, source_modified_time, source_created_at,
                synced_at, is_active
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (content_id) DO UPDATE SET
                title = EXCLUDED.title,
                overview = EXCLUDED.overview,
                overview_hash = EXCLUDED.overview_hash,
                theme = EXCLUDED.theme,
                taketime = EXCLUDED.taketime,
                taketime_minutes = EXCLUDED.taketime_minutes,
                distance = EXCLUDED.distance,
                distance_km = EXCLUDED.distance_km,
                schedule = EXCLUDED.schedule,
                infocenter_tourcourse = EXCLUDED.infocenter_tourcourse,
                first_image = EXCLUDED.first_image,
                first_image_cpyrht_div_cd = EXCLUDED.first_image_cpyrht_div_cd,
                l_dong_regn_cd = EXCLUDED.l_dong_regn_cd,
                source_modified_time = EXCLUDED.source_modified_time,
                source_created_at = EXCLUDED.source_created_at,
                synced_at = EXCLUDED.synced_at,
                is_active = TRUE,
                inactive_since = NULL
            """,
            (
                course.content_id,
                course.title,
                course.overview,
                course.overview_hash,
                course.theme,
                course.taketime,
                course.taketime_minutes,
                course.distance,
                course.distance_km,
                course.schedule,
                course.infocenter_tourcourse,
                course.first_image,
                course.first_image_cpyrht_div_cd,
                course.l_dong_regn_cd,
                course.source_modified_time,
                course.source_created_at,
                course.synced_at,
                course.is_active,
            ),
        )

    async def _upsert_raw_snapshot(
        self,
        conn: AsyncConnection,
        raw: CourseRawSnapshot,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {TRAVEL_COURSE_RAW_SNAPSHOTS_TABLE} (content_id, raw_json, fetched_at)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (content_id) DO UPDATE SET
                raw_json = EXCLUDED.raw_json,
                fetched_at = EXCLUDED.fetched_at
            """,
            (raw.content_id, Json(raw.raw_json), raw.fetched_at),
        )

    async def _replace_course_items(
        self,
        conn: AsyncConnection,
        course_content_id: str,
        items: list[CourseItemRecord],
    ) -> None:
        # REPLACE 정책: 한 트랜잭션 안에서 기존 아이템 삭제 후 재삽입
        await conn.execute(
            f"DELETE FROM {COURSE_ITEMS_TABLE} WHERE course_content_id = %s",
            (course_content_id,),
        )

        if not items:
            return

        # FK 안전성: spots에 실제로 존재하는 content_id만 matched_spot_id로 저장.
        # 존재하지 않으면 NULL로 내려서 course_items_matched_spot_id_fkey 위반을 방지한다.
        valid_matched_ids = await self._load_existing_spot_ids(conn, items)

        rows = [
            (
                item.course_content_id,
                item.serial_num,
                item.sub_content_id,
                item.matched_spot_id if item.matched_spot_id in valid_matched_ids else None,
                item.sub_name,
                item.sub_overview,
                item.sub_image,
                item.sub_image_alt,
            )
            for item in items
        ]
        await conn.cursor().executemany(
            f"""
            INSERT INTO {COURSE_ITEMS_TABLE} (
                course_content_id, serial_num, sub_content_id, matched_spot_id,
                sub_name, sub_overview, sub_image, sub_image_alt
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )

    async def _load_existing_spot_ids(
        self,
        conn: AsyncConnection,
        items: list[CourseItemRecord],
    ) -> set[str]:
        candidate_ids = [
            item.matched_spot_id
            for item in items
            if item.matched_spot_id
        ]
        if not candidate_ids:
            return set()

        row = await conn.execute(
            f"""
            SELECT content_id
              FROM {SPOTS_TABLE}
             WHERE content_id = ANY(%s)
            """,
            (candidate_ids,),
        )
        records = await row.fetchall()
        typed_records = cast(list[dict[str, Any]], records)
        return {str(record["content_id"]) for record in typed_records}
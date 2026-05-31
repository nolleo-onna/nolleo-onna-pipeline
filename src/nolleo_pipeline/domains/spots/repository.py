"""Spots 도메인 DB I/O.

[이 파일이 왜 있냐]
- 정규화 모델(ParsedSpot) → DB INSERT/UPDATE 하나의 트랜잭션 안에서.
- operation.md §2 UPSERT/REPLACE 정책 + §14 트랜잭션 경계 강제.

[규약]
- SPOTS / SPOT_DETAILS / SPOTS_RAW_SNAPSHOTS = UPSERT (ON CONFLICT DO UPDATE)
- SPOT_IMAGES = REPLACE (DELETE + INSERT, 같은 트랜잭션 안에서)
- 캐시 컬럼(overview_summary, popularity_score 등)은 다른 잡 소유 → 여기서 안 건드림
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from psycopg import AsyncConnection
from psycopg.types.json import Json

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.domains.spots.models import (
    ParsedSpot,
    SpotCoreRecord,
    SpotDetailsRecord,
    SpotImageRecord,
    SpotRawSnapshot,
)


class SpotsRepository:
    """파이프라인이 사용할 DB I/O 진입점.

    public 메서드 1개(upsert_spot) + 보조 1개(get_overview_hash).
    모든 INSERT/UPDATE/DELETE는 한 ParsedSpot 단위로 단일 트랜잭션.
    """

    async def upsert_spot(self, parsed: ParsedSpot) -> None:
        """ParsedSpot 한 건을 4개 테이블에 분배해서 적재.

        하나라도 실패하면 전체 ROLLBACK. 호출자가 예외 받아서 재시도/skip 결정.
        """
        pool = await get_pool()
        # ⭐ §14: REPLACE 패턴(images)이 들어 있으므로 단일 트랜잭션 강제.
        async with pool.connection() as conn, conn.transaction():
            await self._upsert_core(conn, parsed.core)
            await self._upsert_detail(conn, parsed.detail)
            await self._upsert_raw(conn, parsed.raw)
            await self._replace_images(conn, parsed.content_id, parsed.images)

    async def get_overview_hash(self, content_id: str) -> str | None:
        """SPOT_DETAILS의 현재 overview_hash 조회.

        파이프라인이 sync 전에 호출해서 변경 여부를 미리 판정 가능.
        """
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                "SELECT overview_hash FROM spot_details WHERE content_id = %s",
                (content_id,),
            )
            result = await row.fetchone()
            if result is None:
                return None
            overview_hash: str | None = cast(dict[str, Any], result)["overview_hash"]
            return overview_hash

    async def get_source_modified_times(
        self,
        content_ids: list[str],
    ) -> dict[str, datetime | None]:
        """SPOTS.source_modified_time를 content_id 목록으로 조회.

        상세 4개 endpoint 호출 전에 변경 여부를 선별해 API 호출량을 절감한다.
        """
        if not content_ids:
            return {}
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                """
                SELECT content_id, source_modified_time
                  FROM spots
                 WHERE content_id = ANY(%s)
                """,
                (content_ids,),
            )
            records = await row.fetchall()
            typed_records = cast(list[dict[str, Any]], records)
            return {
                record["content_id"]: record["source_modified_time"]
                for record in typed_records
            }

    async def count_active(
        self,
        *,
        regions: list[str],
        content_type_ids: list[str],
    ) -> int:
        """비활성 비율 가드의 분모 — 대상 범위의 활성 row 총수.

        `source_tour_api=TRUE`만 카운트. 수기 등록 row는 가드 분모에서도 제외.
        """
        if not regions or not content_type_ids:
            return 0
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                """
                SELECT count(*) AS total
                  FROM spots
                 WHERE l_dong_regn_cd = ANY(%s)
                   AND content_type_id = ANY(%s)
                   AND source_tour_api = TRUE
                   AND is_active = TRUE
                """,
                (regions, content_type_ids),
            )
            result = await row.fetchone()
            if result is None:
                return 0
            return int(cast(dict[str, Any], result)["total"])

    async def count_deactivation_candidates(
        self,
        *,
        regions: list[str],
        content_type_ids: list[str],
        sync_started_at: datetime,
    ) -> int:
        """비활성 비율 가드의 분자 — dry-run 카운트.

        실제 UPDATE 전에 비율을 계산하기 위한 사전 조회.
        """
        if not regions or not content_type_ids:
            return 0
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                """
                SELECT count(*) AS total
                  FROM spots
                 WHERE l_dong_regn_cd = ANY(%s)
                   AND content_type_id = ANY(%s)
                   AND source_tour_api = TRUE
                   AND is_active = TRUE
                   AND synced_at < %s
                """,
                (regions, content_type_ids, sync_started_at),
            )
            result = await row.fetchone()
            if result is None:
                return 0
            return int(cast(dict[str, Any], result)["total"])

    async def deactivate_missing(
        self,
        *,
        regions: list[str],
        content_type_ids: list[str],
        sync_started_at: datetime,
        inactive_since: datetime,
    ) -> list[str]:
        """이번 회차에서 사라진 active row를 비활성화.

        호출자가 가드 1·2·3·4를 통과시킨 뒤에만 호출 (정책-인프라 분리).
        재등장 복구는 `_upsert_core` ON CONFLICT 절이 담당 → 본 메서드는 단방향.

        Args:
            regions: 이번 회차가 풀스캔한 시도 코드(`l_dong_regn_cd`).
            content_type_ids: 이번 회차가 풀스캔한 contentTypeId 전체.
            sync_started_at: sync 본체 시작 직전 캡처한 시각. 이 시각 이전에
                synced_at이 기록된 row만 비활성 후보(이번 회차 갱신분 제외).
            inactive_since: 비활성 시점으로 박을 시각. 모든 row가 동일 값.

        Returns:
            비활성된 content_id 목록. 멱등 — 이미 비활성 row는 영향 없음.
        """
        if not regions or not content_type_ids:
            return []
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            row = await conn.execute(
                """
                UPDATE spots
                   SET is_active      = FALSE,
                       inactive_since = %s
                 WHERE l_dong_regn_cd = ANY(%s)
                   AND content_type_id = ANY(%s)
                   AND source_tour_api = TRUE
                   AND is_active = TRUE
                   AND synced_at < %s
                RETURNING content_id
                """,
                (inactive_since, regions, content_type_ids, sync_started_at),
            )
            records = await row.fetchall()
            typed_records = cast(list[dict[str, Any]], records)
            return [str(record["content_id"]) for record in typed_records]

    # ─── 내부 메서드들 ────────────────────────────────────────

    async def _upsert_core(self, conn: AsyncConnection, core: SpotCoreRecord) -> None:
        """SPOTS UPSERT.

        EXCLUDED는 PostgreSQL의 ON CONFLICT 전용 키워드 — "이번에 INSERT 시도했던 값".
        캐시 컬럼(overview_summary, popularity_score 등)은 안 건드림 → 다른 잡이 갱신.
        """
        await conn.execute(
            """
            INSERT INTO spots (
                content_id, content_type_id, title,
                source_tour_api, source_busan_food,
                map_x, map_y,
                l_dong_regn_cd, l_dong_signgu_cd,
                lcls_systm_1, lcls_systm_2, lcls_systm_3,
                first_image, first_image2, first_image_cpyrht_div_cd,
                source_modified_time, synced_at, is_active
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
            ON CONFLICT (content_id) DO UPDATE SET
                content_type_id      = EXCLUDED.content_type_id,
                title                = EXCLUDED.title,
                source_tour_api      = EXCLUDED.source_tour_api,
                source_busan_food    = EXCLUDED.source_busan_food OR spots.source_busan_food,
                map_x                = EXCLUDED.map_x,
                map_y                = EXCLUDED.map_y,
                l_dong_regn_cd       = EXCLUDED.l_dong_regn_cd,
                l_dong_signgu_cd     = EXCLUDED.l_dong_signgu_cd,
                lcls_systm_1         = EXCLUDED.lcls_systm_1,
                lcls_systm_2         = EXCLUDED.lcls_systm_2,
                lcls_systm_3         = EXCLUDED.lcls_systm_3,
                first_image          = EXCLUDED.first_image,
                first_image2         = EXCLUDED.first_image2,
                first_image_cpyrht_div_cd = EXCLUDED.first_image_cpyrht_div_cd,
                source_modified_time = EXCLUDED.source_modified_time,
                synced_at            = EXCLUDED.synced_at,
                is_active            = TRUE,            -- 재등장 시 재활성화
                inactive_since       = NULL
            """,
            (
                core.content_id, core.content_type_id, core.title,
                core.source_tour_api, core.source_busan_food,
                core.map_x, core.map_y,
                core.l_dong_regn_cd, core.l_dong_signgu_cd,
                core.lcls_systm_1, core.lcls_systm_2, core.lcls_systm_3,
                core.first_image, core.first_image2, core.first_image_cpyrht_div_cd,
                core.source_modified_time, core.synced_at, core.is_active,
            ),
        )

    async def _upsert_detail(self, conn: AsyncConnection, detail: SpotDetailsRecord) -> None:
        """SPOT_DETAILS UPSERT.

        business_hours / business_hours_* 컬럼은 LLM 단계 소유 → 여기서 안 건드림.
        """
        await conn.execute(
            """
            INSERT INTO spot_details (
                content_id, tel, tel_name, homepage,
                addr1, addr2, zipcode,
                overview, overview_hash, intro,
                parking_available, source_created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (content_id) DO UPDATE SET
                tel               = EXCLUDED.tel,
                tel_name          = EXCLUDED.tel_name,
                homepage          = EXCLUDED.homepage,
                addr1             = EXCLUDED.addr1,
                addr2             = EXCLUDED.addr2,
                zipcode           = EXCLUDED.zipcode,
                overview          = EXCLUDED.overview,
                overview_hash     = EXCLUDED.overview_hash,
                intro             = EXCLUDED.intro,
                parking_available = EXCLUDED.parking_available,
                source_created_at = EXCLUDED.source_created_at
            """,
            (
                detail.content_id, detail.tel, detail.tel_name, detail.homepage,
                detail.addr1, detail.addr2, detail.zipcode,
                detail.overview, detail.overview_hash,
                Json(detail.intro) if detail.intro is not None else None,  # JSONB 래핑
                detail.parking_available, detail.source_created_at,
            ),
        )

    async def _upsert_raw(self, conn: AsyncConnection, raw: SpotRawSnapshot) -> None:
        """SPOTS_RAW_SNAPSHOTS UPSERT (최신만 보관, 이력 X)."""
        await conn.execute(
            """
            INSERT INTO spots_raw_snapshots (content_id, raw_json, fetched_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (content_id) DO UPDATE SET
                raw_json   = EXCLUDED.raw_json,
                fetched_at = EXCLUDED.fetched_at
            """,
            (raw.content_id, Json(raw.raw_json), raw.fetched_at),
        )

    async def _replace_images(
        self,
        conn: AsyncConnection,
        content_id: str,
        images: list[SpotImageRecord],
    ) -> None:
        """SPOT_IMAGES REPLACE: 갤러리 통째 교체.

        operation.md §2 + §14: DELETE + INSERT를 같은 트랜잭션 안에서 → 깜빡임 없음.
        호출자(upsert_spot)가 이미 transaction() 블록 안에 있어서 여기선 추가 트랜잭션 X.
        """
        # 기존 이미지 전부 삭제
        await conn.execute(
            "DELETE FROM spot_images WHERE content_id = %s",
            (content_id,),
        )

        if not images:
            return                                                # 새 이미지 없으면 끝

        # executemany로 일괄 INSERT
        await conn.cursor().executemany(
            """
            INSERT INTO spot_images (
                content_id, origin_img_url, small_img_url, img_name, cpyrht_div_cd, serial_num
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    img.content_id,
                    img.origin_img_url,
                    img.small_img_url,
                    img.img_name,
                    img.cpyrht_div_cd,
                    img.serial_num,
                )
                for img in images
            ],
        )

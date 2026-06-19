"""Congestion 도메인 DB I/O.

[이 파일이 왜 있냐]
- CongestionForecastRecord → SPOT_CONGESTION_FORECAST 적재 (partial UK 2종 분기)
- raw_tats_name + signgu_cd → SPOTS 룰 1단계 매칭 (ADR 0001)
- SPOTS 캐시 컬럼 (today/upcoming concentration) 갱신
- 7일 이전 예측 row cleanup

[규약]
- SPOT_CONGESTION_FORECAST = UPSERT (matched/unmatched 인덱스별 분리 적재)
- SPOTS.{today_concentration_rate, upcoming_concentration_avg, concentration_updated_at}
  은 본 도메인이 RW 권한. 다른 컬럼은 안 건드림.
- source='tourapi'만 적재 (CHECK 제약 chk_spot_congestion_trace_consistency:
  source='llm'은 trace NOT NULL 필수, 'tourapi'/'rule'은 trace IS NULL).
  'llm'/'rule' source 적재는 후속 PR (LLM 회색지대 매칭 / rule 기반 추정)에서 도입.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, cast

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.domains.congestion.models import CongestionForecastRecord

# 접두사 컨벤션(sp_/cd_) 적용된 실제 테이블명. RDS 스키마/alembic과 정합.
SPOTS_TABLE = "sp_spots"
LDONG_CODES_TABLE = "cd_ldong_codes"
# ⚠ 미존재 테이블: 혼잡도 도메인 스키마가 아직 alembic/RDS에 없음.
#    별도 마이그레이션(0011_create_congestion_domain 등) 추가 전까지 이 도메인
#    적재/조회는 동작하지 않는다. 상수만 모아두어 추후 마이그레이션 시 일괄 정합.
SPOT_CONGESTION_FORECAST_TABLE = "spot_congestion_forecast"


class CongestionRepository:
    """파이프라인이 사용할 DB I/O 진입점."""

    # ─── 1. UPSERT (partial UK 2종) ──────────────────────────────

    async def upsert_forecasts(
        self,
        records: list[CongestionForecastRecord],
    ) -> tuple[int, int]:
        """매칭/언매칭 record를 partial UK별로 분리해 batch upsert.

        Returns:
            (matched_count, unmatched_count)

        한 트랜잭션 — 둘 중 하나라도 실패하면 전체 ROLLBACK.

        Raises:
            ValueError: source != 'tourapi'인 record가 섞여 있으면 즉시 raise.
                DB CHECK 위반보다 명확한 에러로 호출자에게 전달.
        """
        if not records:
            return 0, 0

        # source='tourapi'만 처리 — 잘못된 source는 즉시 raise
        invalid_sources = {r.source for r in records if r.source != "tourapi"}
        if invalid_sources:
            raise ValueError(
                f"upsert_forecasts: 본 메서드는 source='tourapi'만 처리. "
                f"받은 source={invalid_sources} — 'llm'/'rule' 적재는 후속 PR에서 분기 도입 예정."
            )

        matched = [r for r in records if r.content_id is not None]
        unmatched = [r for r in records if r.content_id is None]

        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            if matched:
                await conn.cursor().executemany(
                    f"""
                    INSERT INTO {SPOT_CONGESTION_FORECAST_TABLE} (
                        content_id, area_cd, signgu_cd, raw_tats_name,
                        area_name, signgu_name, base_ymd,
                        concentration_rate, level, source, trace, fetched_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, NULL, %s
                    )
                    ON CONFLICT (content_id, base_ymd, source)
                        WHERE content_id IS NOT NULL
                    DO UPDATE SET
                        area_cd            = EXCLUDED.area_cd,
                        signgu_cd          = EXCLUDED.signgu_cd,
                        raw_tats_name      = EXCLUDED.raw_tats_name,
                        area_name          = EXCLUDED.area_name,
                        signgu_name        = EXCLUDED.signgu_name,
                        concentration_rate = EXCLUDED.concentration_rate,
                        level              = EXCLUDED.level,
                        fetched_at         = EXCLUDED.fetched_at
                    """,
                    [
                        (
                            r.content_id, r.area_cd, r.signgu_cd, r.raw_tats_name,
                            r.area_name, r.signgu_name, r.base_ymd,
                            r.concentration_rate, r.level, r.source, r.fetched_at,
                        )
                        for r in matched
                    ],
                )

            if unmatched:
                await conn.cursor().executemany(
                    f"""
                    INSERT INTO {SPOT_CONGESTION_FORECAST_TABLE} (
                        content_id, area_cd, signgu_cd, raw_tats_name,
                        area_name, signgu_name, base_ymd,
                        concentration_rate, level, source, trace, fetched_at
                    ) VALUES (
                        NULL, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, NULL, %s
                    )
                    ON CONFLICT (area_cd, signgu_cd, raw_tats_name, base_ymd, source)
                        WHERE content_id IS NULL
                    DO UPDATE SET
                        area_name          = EXCLUDED.area_name,
                        signgu_name        = EXCLUDED.signgu_name,
                        concentration_rate = EXCLUDED.concentration_rate,
                        level              = EXCLUDED.level,
                        fetched_at         = EXCLUDED.fetched_at
                    """,
                    [
                        (
                            r.area_cd, r.signgu_cd, r.raw_tats_name,
                            r.area_name, r.signgu_name, r.base_ymd,
                            r.concentration_rate, r.level, r.source, r.fetched_at,
                        )
                        for r in unmatched
                    ],
                )

        return len(matched), len(unmatched)

    # ─── 2. 매칭 (raw_tats_name → content_id) ───────────────────

    async def match_by_raw_name_in_signgu(
        self,
        *,
        raw_tats_name: str,
        signgu_cd: str,
    ) -> str | None:
        """ADR 0001 1단계 룰 매칭 — 같은 시군구 + 괄호/공백 정규화 후 이름 일치.

        한국어 관광지 이름 변형 패턴 흡수:
            1. 괄호 동음이의 — "대각사(부산)" / "이기대 (부산 국가지질공원)"
               → 괄호와 그 안 내용 통째 제거.
            2. 띄어쓰기 변형 — "해운대 해수욕장" / "해운대해수욕장"
               → 잔여 공백 제거.

        양쪽(DB title + 입력 raw_tats_name)에 같은 정규화 적용해서 비교.

        회색지대(약어/한영 — "BEXCO" vs "벡스코" 류, SPOTS 자체 부재)는 None 반환
        → 호출자가 unmatched로 적재. 후속 PR(`feat/spots-congestion-rematch`)에서
        SPOTS 적재 정책 보완 + LLM 회색지대 매칭 도입.

        성능 노트:
            regexp_replace는 일반 title 인덱스를 타지 못함. 다만 (l_dong_signgu_cd,
            is_active) 필터로 시군구당 ~50 row(부산 기준)까지 좁혀진 후 평가하므로
            buffer scan으로 충분. 전국 확장 시 시군구당 200+ row 되면 표현식 인덱스
            추가 검토 — 별도 PR.

        결정성:
            정규화 후 같은 시군구에 동일 이름 spot이 여러 개일 때 어떤 row를 반환할지
            안정 — `ORDER BY content_id`로 항상 같은 row를 선택해서 운영 중 "왜
            오늘은 다른 content_id에 붙었지?" 디버깅 회피.
        """
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                rf"""
                SELECT content_id
                  FROM {SPOTS_TABLE}
                 WHERE l_dong_signgu_cd = %s
                   AND is_active        = TRUE
                   AND regexp_replace(
                         regexp_replace(title, '\s*\([^)]*\)\s*', '', 'g'),
                         '\s+', '', 'g'
                       )
                     = regexp_replace(
                         regexp_replace(%s, '\s*\([^)]*\)\s*', '', 'g'),
                         '\s+', '', 'g'
                       )
                 ORDER BY content_id                          --  결정성 보장
                 LIMIT 1
                """,
                (signgu_cd, raw_tats_name),
            )
            result = await row.fetchone()
            if result is None:
                return None
            return cast(str, cast(dict[str, Any], result)["content_id"])

    # ─── 3. SPOTS 캐시 갱신 ─────────────────────────────────────

    async def refresh_today_concentration_cache(
        self,
        *,
        today: date,
        updated_at: datetime,
    ) -> int:
        """SPOTS의 혼잡도 캐시 3컬럼 UPDATE.

        - today_concentration_rate: base_ymd = TODAY (KST)
        - upcoming_concentration_avg: base_ymd ∈ [TODAY+1, TODAY+3] 평균 (3일, today 미포함)
        - concentration_updated_at: 호출자가 박은 updated_at

        오늘 forecast가 있는 spot만 UPDATE — 매칭 실패 spot은 어제 값 유지
        (의도적 trade-off: 전체 spot scan 회피로 인덱스 갱신 비용 절약,
         stale은 `concentration_updated_at`로 추적).

        비활성 spot(is_active=FALSE)은 UPDATE 대상에서 제외 — 비활성 spot은
        조회 자체에서 빠지므로 캐시 write가 무의미.

        Returns:
            UPDATE된 row 수 (= SYNC_LOGS.metadata.cache_updated_count)
        """
        tomorrow = today + timedelta(days=1)
        three_days_later = today + timedelta(days=3)

        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            row = await conn.execute(
                """
                WITH today_data AS (
                    SELECT content_id, concentration_rate
                      FROM {SPOT_CONGESTION_FORECAST_TABLE}
                     WHERE base_ymd     = %s
                       AND content_id  IS NOT NULL
                       AND source       = 'tourapi'
                ),
                upcoming_data AS (
                    SELECT content_id,
                           AVG(concentration_rate)::numeric(5,2) AS avg_rate
                      FROM {SPOT_CONGESTION_FORECAST_TABLE}
                     WHERE base_ymd BETWEEN %s AND %s
                       AND content_id  IS NOT NULL
                       AND source       = 'tourapi'
                     GROUP BY content_id
                )
                UPDATE {SPOTS_TABLE} sc
                   SET today_concentration_rate    = td.concentration_rate,
                       upcoming_concentration_avg = ud.avg_rate,
                       concentration_updated_at   = %s
                  FROM today_data td
                  LEFT JOIN upcoming_data ud ON ud.content_id = td.content_id
                 WHERE sc.content_id = td.content_id
                   AND sc.is_active   = TRUE                    -- 비활성 spot 제외
                """,
                (today, tomorrow, three_days_later, updated_at),
            )
            return row.rowcount

    # ─── 4. cleanup (7일 이전) ──────────────────────────────────

    async def purge_old_forecasts(self, *, cutoff_date: date) -> int:
        """`base_ymd < cutoff_date` row 일괄 삭제.

        Returns:
            삭제된 row 수.
        """
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            row = await conn.execute(
                """
                DELETE FROM spot_congestion_forecast
                 WHERE base_ymd < %s
                """,
                (cutoff_date,),
            )
            return row.rowcount

    # ─── 5. 시군구 코드 조회 (LDONG_CODES, area_cd별) ───────────

    async def list_signgu_codes_by_area(self, area_cd: str) -> list[tuple[str, str]]:
        """LDONG_CODES에서 특정 area_cd의 시군구 코드 목록 조회.

        부산(area_cd='26')은 16개 시군구. 전국 확장 시 그대로 재사용 가능.

        Returns:
            [(area_cd, signgu_cd), ...] 튜플 목록.
        """
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                f"""
                SELECT regn_cd, signgu_cd
                  FROM {LDONG_CODES_TABLE}
                 WHERE regn_cd = %s
                 ORDER BY signgu_cd
                """,
                (area_cd,),
            )
            records = await row.fetchall()
            typed = cast(list[dict[str, Any]], records)
            return [
                (str(r["regn_cd"]), str(r["signgu_cd"]))
                for r in typed
            ]
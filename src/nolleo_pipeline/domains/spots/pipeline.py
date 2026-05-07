"""Spots 도메인 sync 오케스트레이션.

[이 파일이 왜 있냐]
- 위 client + parser + repository를 묶어 "한 번의 sync 잡"으로 만듦.
- SYNC_LOGS에 시작/끝/메트릭 자동 기록.
- 1건 실패가 전체 잡을 죽이지 않도록 per-spot try/except.

[흐름]
list_by_area (페이지 돌기) → 각 item마다 fetch_full → parse → upsert
                                                          ↓
                                                   ctx 카운트 누적
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.common.http import build_http_client
from nolleo_pipeline.common.sync_logs import sync_log_run
from nolleo_pipeline.common.timezone import now_utc, parse_tourapi_timestamp
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.spots.client import TourApiSpotClient
from nolleo_pipeline.domains.spots.parser import parse_spot
from nolleo_pipeline.domains.spots.repository import SpotsRepository

# 부산 법정동 시도 코드. KorService2 areaBasedList2의 lDongRegnCd 값.
# (구 KorService 1.x의 areaCode="6"과는 다른 체계 — 매뉴얼 v4.4 §1 참조)
DEFAULT_BUSAN_REGN_CD = "26"

# 동기화할 contentTypeId. 12=관광지, 14=문화시설, 39=음식점.
SPOT_CONTENT_TYPE_IDS = ("12", "14", "39")
TYPE_BUDGET_WEIGHTS: dict[str, float] = {"12": 0.5, "14": 0.25, "39": 0.25}


async def run_tourapi_spots_sync(
    *,
    l_dong_regn_cd: str = DEFAULT_BUSAN_REGN_CD,
    content_type_ids: tuple[str, ...] = SPOT_CONTENT_TYPE_IDS,
    num_of_rows: int = 100,
    max_pages: int | None = None,
) -> None:
    """TourAPI 관광지 동기화 잡 진입점.

    Args:
        l_dong_regn_cd: 법정동 시도 코드. 기본 부산("26").
        content_type_ids: 관광지(12), 문화시설(14), 음식점(39).
        num_of_rows: 한 페이지당 행 수 (TourAPI 권고: 최대 100).
        max_pages: 디버그용 페이지 제한. None이면 끝까지.
    """
    settings = get_settings()
    repo = SpotsRepository()
    api_budget_limit = settings.daily_api_call_limit
    previous_state = await _load_previous_sync_state("tourapi_spots_sync")
    previous_cursors = previous_state.get("next_cursor_by_type", {})
    terminal_page_by_type = previous_state.get("terminal_page_by_type", {})
    bootstrap_complete_prev = bool(previous_state.get("bootstrap_complete"))
    bootstrap_mode = not bootstrap_complete_prev
    type_budget_limits = _build_type_budgets(
        total_limit=api_budget_limit,
        content_type_ids=content_type_ids,
        bootstrap_mode=bootstrap_mode,
    )

    # async with sync_log_run(...) → SYNC_LOGS에 'running' 행 INSERT,
    # 블록 정상 종료 시 'success'로 마감, 예외 시 'failed' + error_message 기록.
    async with sync_log_run("tourapi_spots_sync") as ctx:
        ctx.metadata.setdefault("skip_unchanged_count", 0)
        ctx.metadata.setdefault("skip_invalid_count", 0)
        ctx.metadata.setdefault("stopped_by_budget", False)
        ctx.metadata.setdefault("next_cursor", None)
        ctx.metadata.setdefault("bootstrap_mode", bootstrap_mode)
        ctx.metadata.setdefault("api_budget_limit", api_budget_limit)
        ctx.metadata.setdefault("budget_by_type", type_budget_limits)
        ctx.metadata.setdefault("api_calls_by_type", {})
        ctx.metadata.setdefault("next_cursor_by_type", {})
        ctx.metadata.setdefault("terminal_page_by_type", dict(terminal_page_by_type))
        ctx.metadata.setdefault("bootstrap_complete", bootstrap_complete_prev)
        # ── 비활성 처리 metadata (ADR 0003) ──
        ctx.metadata.setdefault("deactivated_count", 0)
        ctx.metadata.setdefault("deactivation_skipped", None)
        ctx.metadata.setdefault("deactivation_skip_reason", None)
        ctx.metadata.setdefault("deactivation_failure_rate", None)
        ctx.metadata.setdefault("deactivation_ratio", None)

        sync_started_at = now_utc()
        ctx.metadata["sync_started_at"] = sync_started_at.isoformat()

        # async with build_http_client() → httpx 커넥션 풀 자동 정리.
        async with build_http_client() as http:
            client = TourApiSpotClient(http, service_key=settings.tour_api_key)

            for content_type_id in content_type_ids:
                # 증분 모드(bootstrap 완료 후)에서는 항상 page 1에서 최신 변경분을 먼저 본다.
                # bootstrap 중에만 타입별 resume cursor를 적용해 중단 지점에서 이어간다.
                cursor_for_type = previous_cursors.get(content_type_id) if bootstrap_mode else None
                stopped, reached_terminal = await _sync_one_content_type(
                    client=client,
                    repo=repo,
                    ctx=ctx,
                    l_dong_regn_cd=l_dong_regn_cd,
                    content_type_id=content_type_id,
                    num_of_rows=num_of_rows,
                    max_pages=max_pages,
                    api_budget_limit=api_budget_limit,
                    type_budget_limit=type_budget_limits[content_type_id],
                    start_page=_extract_cursor_page(cursor_for_type),
                    resume_cursor=cursor_for_type,
                    bootstrap_mode=bootstrap_mode,
                )
                ctx.metadata["terminal_page_by_type"][content_type_id] = reached_terminal
                if stopped:
                    break

        # http client 블록 외부, sync_log_run 블록 내부 (ADR 0003)
        ctx.metadata["bootstrap_complete"] = all(
            bool(ctx.metadata["terminal_page_by_type"].get(content_type_id, False))
            for content_type_id in content_type_ids
        )

        await _deactivate_missing_if_safe(
            repo=repo,
            ctx=ctx,
            regions=[l_dong_regn_cd],
            content_type_ids=list(content_type_ids),
            sync_started_at=sync_started_at,
            max_failure_rate=settings.spots_deactivate_max_failure_rate,
            max_deactivation_ratio=settings.spots_deactivate_max_ratio,
        )


async def _sync_one_content_type(
    *,
    client: TourApiSpotClient,
    repo: SpotsRepository,
    ctx: Any,                                                     # SyncLogContext
    l_dong_regn_cd: str,
    content_type_id: str,
    num_of_rows: int,
    max_pages: int | None,
    api_budget_limit: int,
    type_budget_limit: int,
    start_page: int,
    resume_cursor: dict[str, Any] | None,
    bootstrap_mode: bool,
) -> tuple[bool, bool]:
    """단일 contentTypeId 동기화 — 페이지 끝까지 또는 max_pages까지."""
    page = start_page
    type_api_calls_used = 0
    last_cursor = _build_cursor(
        page=start_page,
        modifiedtime=(resume_cursor or {}).get("modifiedtime") if resume_cursor else None,
        content_id=(resume_cursor or {}).get("content_id") if resume_cursor else None,
    )
    while True:
        if max_pages is not None and page > max_pages:
            _set_type_cursor(ctx, content_type_id, last_cursor)
            return False, False

        # 1) 목록 조회
        if ctx.api_calls_used >= api_budget_limit:
            _mark_budget_stop(
                ctx,
                content_type_id=content_type_id,
                page=page,
                modifiedtime=None,
                content_id=None,
                api_budget_limit=api_budget_limit,
            )
            return True, False
        if type_api_calls_used >= type_budget_limit:
            _mark_type_budget_stop(
                ctx,
                content_type_id=content_type_id,
                page=page,
                modifiedtime=None,
                content_id=None,
                type_budget_limit=type_budget_limit,
            )
            return False, False
        ctx.api_calls_used += 1
        type_api_calls_used += 1
        list_payload = await client.list_by_area(
            l_dong_regn_cd=l_dong_regn_cd,
            content_type_id=content_type_id,
            page=page,
            num_of_rows=num_of_rows,
        )
        _set_type_api_calls_used(ctx, content_type_id, type_api_calls_used)
        items = _extract_list_items(list_payload)

        # 페이지 비었으면 끝
        if not items:
            _set_type_cursor(ctx, content_type_id, last_cursor)
            return False, True
        items = _apply_resume_cursor(items, page=page, resume_cursor=resume_cursor)
        if not items:
            page += 1
            continue

        content_ids = [
            str(item["contentid"])
            for item in items
            if isinstance(item.get("contentid"), str | int)
        ]
        existing_modified_map = await repo.get_source_modified_times(content_ids)

        # 2) 각 item 처리
        page_unchanged_count = 0
        for item in items:
            ctx.records_fetched += 1
            try:
                content_id = _extract_content_id(item)
                modifiedtime_text = _extract_modifiedtime_text(item)
                modifiedtime = parse_tourapi_timestamp(modifiedtime_text)
                if content_id is None:
                    ctx.metadata["skip_invalid_count"] += 1
                    continue
                last_cursor = _build_cursor(
                    page=page,
                    modifiedtime=modifiedtime_text,
                    content_id=content_id,
                )

                if _is_unchanged(
                    incoming_modified=modifiedtime,
                    stored_modified=existing_modified_map.get(content_id),
                ):
                    page_unchanged_count += 1
                    ctx.metadata["skip_unchanged_count"] += 1
                    continue

                if ctx.api_calls_used + 4 > api_budget_limit:
                    _mark_budget_stop(
                        ctx,
                        content_type_id=content_type_id,
                        page=page,
                        modifiedtime=modifiedtime_text,
                        content_id=content_id,
                        api_budget_limit=api_budget_limit,
                    )
                    return True, False
                if type_api_calls_used + 4 > type_budget_limit:
                    _mark_type_budget_stop(
                        ctx,
                        content_type_id=content_type_id,
                        page=page,
                        modifiedtime=modifiedtime_text,
                        content_id=content_id,
                        type_budget_limit=type_budget_limit,
                    )
                    _set_type_api_calls_used(ctx, content_type_id, type_api_calls_used)
                    _set_type_cursor(ctx, content_type_id, last_cursor)
                    return False, False

                await _process_one_spot(client, repo, ctx, item, content_type_id)
                type_api_calls_used += 4
                _set_type_api_calls_used(ctx, content_type_id, type_api_calls_used)
                ctx.records_upserted += 1
            except Exception as exc:                              # noqa: BLE001
                # per-spot 실패는 잡 전체 실패로 안 만듦. 메트릭에만 누적.
                ctx.records_failed += 1
                ctx.metadata.setdefault("errors", []).append(
                    {"content_id": item.get("contentid"), "error": str(exc)[:300]}
                )

        # `arrange=C`(수정일 내림차순) 전제일 때만 안전한 조기 종료.
        # 현재 페이지가 전부 "변경 없음"이면 다음 페이지는 더 과거 데이터라
        # 즉시 종료해도 누락이 없다.
        if not bootstrap_mode and page_unchanged_count == len(items):
            _set_type_cursor(ctx, content_type_id, last_cursor)
            return False, True

        # 3) 페이지 종료 조건 (응답이 num_of_rows보다 적으면 마지막 페이지)
        if len(items) < num_of_rows:
            _set_type_cursor(ctx, content_type_id, last_cursor)
            return False, True
        page += 1

    return False, False


async def _process_one_spot(
    client: TourApiSpotClient,
    repo: SpotsRepository,
    ctx: Any,
    list_item: dict[str, Any],
    content_type_id: str,
) -> None:
    """단일 스팟: 4 endpoint fetch → parse → upsert."""
    content_id = str(list_item["contentid"])
    actual_content_type = str(list_item.get("contenttypeid") or content_type_id)

    # 4 endpoint 병렬 호출 (이게 핵심 비용)
    ctx.api_calls_used += 4
    endpoints = await client.fetch_full(
        content_id=content_id,
        content_type_id=actual_content_type,
    )

    # parse 시점에 박을 시각 — UTC, timezone-aware (operation.md §11)
    fetched_at = now_utc()
    synced_at = fetched_at                                        # 같은 시점으로 통일

    parsed = parse_spot(endpoints, synced_at=synced_at, fetched_at=fetched_at)

    # 단일 트랜잭션으로 4테이블 적재 (repository가 강제)
    await repo.upsert_spot(parsed)


def _extract_list_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """areaBasedList2 응답에서 item list 추출.

    응답 형태에 따라 list / dict / 누락 모두 가능. 일관되게 list로 정규화.
    """
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
    if isinstance(value, str | int):
        text = str(value).strip()
        return text or None
    return None


def _extract_modifiedtime_text(item: dict[str, Any]) -> str | None:
    value = item.get("modifiedtime")
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int):
        return str(value)
    return None


def _is_unchanged(
    *,
    incoming_modified: datetime | None,
    stored_modified: datetime | None,
) -> bool:
    if incoming_modified is None or stored_modified is None:
        return False
    return incoming_modified == stored_modified


def _mark_budget_stop(
    ctx: Any,
    *,
    content_type_id: str,
    page: int,
    modifiedtime: str | None,
    content_id: str | None,
    api_budget_limit: int,
) -> None:
    ctx.metadata["stopped_by_budget"] = True
    ctx.metadata["api_budget_limit"] = api_budget_limit
    ctx.metadata["next_cursor"] = {
        "content_type_id": content_type_id,
        "page": page,
        "modifiedtime": modifiedtime,
        "content_id": content_id,
    }
    if content_type_id:
        _set_type_cursor(
            ctx,
            content_type_id,
            _build_cursor(page=page, modifiedtime=modifiedtime, content_id=content_id),
        )


def _mark_type_budget_stop(
    ctx: Any,
    *,
    content_type_id: str,
    page: int,
    modifiedtime: str | None,
    content_id: str | None,
    type_budget_limit: int,
) -> None:
    ctx.metadata.setdefault("type_budget_stopped", {})
    ctx.metadata["type_budget_stopped"][content_type_id] = True
    ctx.metadata.setdefault("type_budget_limit_by_type", {})
    ctx.metadata["type_budget_limit_by_type"][content_type_id] = type_budget_limit
    _set_type_cursor(
        ctx,
        content_type_id,
        _build_cursor(page=page, modifiedtime=modifiedtime, content_id=content_id),
    )


def _set_type_api_calls_used(ctx: Any, content_type_id: str, value: int) -> None:
    ctx.metadata.setdefault("api_calls_by_type", {})
    ctx.metadata["api_calls_by_type"][content_type_id] = value


def _set_type_cursor(ctx: Any, content_type_id: str, cursor: dict[str, Any]) -> None:
    ctx.metadata.setdefault("next_cursor_by_type", {})
    ctx.metadata["next_cursor_by_type"][content_type_id] = cursor


def _build_cursor(*, page: int, modifiedtime: str | None, content_id: str | None) -> dict[str, Any]:
    return {
        "page": page,
        "modifiedtime": modifiedtime,
        "content_id": content_id,
    }


def _build_type_budgets(
    *,
    total_limit: int,
    content_type_ids: tuple[str, ...],
    bootstrap_mode: bool,
) -> dict[str, int]:
    if not content_type_ids:
        return {}
    if total_limit <= 0:
        return {content_type_id: 0 for content_type_id in content_type_ids}

    budgets: dict[str, int] = {}
    if bootstrap_mode:
        base = total_limit // len(content_type_ids)
        budgets = {content_type_id: base for content_type_id in content_type_ids}
    else:
        weighted_sum = sum(
            TYPE_BUDGET_WEIGHTS.get(content_type_id, 1.0)
            for content_type_id in content_type_ids
        )
        for content_type_id in content_type_ids:
            weight = TYPE_BUDGET_WEIGHTS.get(content_type_id, 1.0)
            budgets[content_type_id] = int(total_limit * (weight / weighted_sum))

    used = sum(budgets.values())
    remainder = total_limit - used
    idx = 0
    ordered_ids = list(content_type_ids)
    while remainder > 0:
        target = ordered_ids[idx % len(ordered_ids)]
        budgets[target] += 1
        remainder -= 1
        idx += 1
    return budgets


def _extract_cursor_page(cursor: dict[str, Any] | None) -> int:
    if not cursor:
        return 1
    page = cursor.get("page")
    if isinstance(page, int) and page >= 1:
        return page
    if isinstance(page, str) and page.isdigit():
        value = int(page)
        return value if value >= 1 else 1
    return 1


def _apply_resume_cursor(
    items: list[dict[str, Any]],
    *,
    page: int,
    resume_cursor: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not resume_cursor:
        return items
    resume_page = _extract_cursor_page(resume_cursor)
    if page != resume_page:
        return items

    target_content_id = resume_cursor.get("content_id")
    target_modifiedtime = resume_cursor.get("modifiedtime")
    if target_content_id is None and target_modifiedtime is None:
        return items

    for index, item in enumerate(items):
        content_id = _extract_content_id(item)
        modifiedtime = _extract_modifiedtime_text(item)
        if content_id == target_content_id and modifiedtime == target_modifiedtime:
            return items[index + 1:]
    return items


async def _deactivate_missing_if_safe(
    *,
    repo: SpotsRepository,
    ctx: Any,
    regions: list[str],
    content_type_ids: list[str],
    sync_started_at: datetime,
    max_failure_rate: float,
    max_deactivation_ratio: float,
) -> None:
    """비활성 안전 가드 4종 평가 후 통과 시에만 deactivate_missing 실행 (ADR 0003).

    가드:
    1. bootstrap_complete — 모든 contentType이 마지막 페이지까지 도달
    2. !stopped_by_budget — 예산 컷으로 중단되지 않음
    3. failure_rate < max_failure_rate
    4. deactivation_ratio < max_deactivation_ratio (dry-run 카운트 기반)

    가드 통과 후 비활성 SQL 실패는 try/except로 흡수 → sync 잡 'failed' 처리 안 함.
    재등장 복구는 _upsert_core ON CONFLICT가 담당 (단방향 책임 분리).
    """
    try:
        # 가드 2를 먼저 평가해 skip reason을 운영 원인에 더 가깝게 남긴다.
        if ctx.metadata.get("stopped_by_budget", False):
            ctx.metadata["deactivation_skipped"] = True
            ctx.metadata["deactivation_skip_reason"] = "stopped_by_budget"
            return

        # 가드 1
        if not ctx.metadata.get("bootstrap_complete", False):
            ctx.metadata["deactivation_skipped"] = True
            ctx.metadata["deactivation_skip_reason"] = "partial_sync"
            return

        # 가드 3
        denominator = max(ctx.records_fetched, 1)
        failure_rate = ctx.records_failed / denominator
        ctx.metadata["deactivation_failure_rate"] = failure_rate
        if failure_rate >= max_failure_rate:
            ctx.metadata["deactivation_skipped"] = True
            ctx.metadata["deactivation_skip_reason"] = "high_failure_rate"
            return

        # 가드 4 — dry-run 카운트로 비율 계산
        active_count = await repo.count_active(
            regions=regions,
            content_type_ids=content_type_ids,
        )
        candidate_count = await repo.count_deactivation_candidates(
            regions=regions,
            content_type_ids=content_type_ids,
            sync_started_at=sync_started_at,
        )
        ratio = (candidate_count / active_count) if active_count > 0 else 0.0
        ctx.metadata["deactivation_ratio"] = ratio
        if ratio >= max_deactivation_ratio:
            ctx.metadata["deactivation_skipped"] = True
            ctx.metadata["deactivation_skip_reason"] = "high_deactivation_ratio"
            return

        # 모든 가드 통과 → 비활성 실행
        deactivated = await repo.deactivate_missing(
            regions=regions,
            content_type_ids=content_type_ids,
            sync_started_at=sync_started_at,
            inactive_since=now_utc(),
        )
        ctx.metadata["deactivated_count"] = len(deactivated)
        ctx.metadata["deactivation_skipped"] = False
        ctx.metadata["deactivation_skip_reason"] = None
    except Exception as exc:  # noqa: BLE001
        # 비활성화 자체 실패는 흡수 — sync 잡 'failed' 만들지 않음 (ADR 0003 §4)
        ctx.metadata["deactivation_skipped"] = True
        ctx.metadata["deactivation_skip_reason"] = "exception"
        ctx.metadata.setdefault("errors", []).append(
            {"stage": "deactivation", "error": str(exc)[:300]}
        )


async def _load_previous_sync_state(job_name: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        row = await conn.execute(
            """
            SELECT metadata
              FROM sync_logs
             WHERE job_name = %s
               AND status = 'success'
               AND metadata IS NOT NULL
             ORDER BY id DESC
             LIMIT 1
            """,
            (job_name,),
        )
        result = await row.fetchone()
        if not result:
            return {}
        result_dict = cast(dict[str, Any], result)
        metadata = result_dict.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                return {}
        if not isinstance(metadata, dict):
            return {}
        next_cursor_by_type = metadata.get("next_cursor_by_type")
        terminal_page_by_type = metadata.get("terminal_page_by_type")

        parsed_cursors = {}
        if isinstance(next_cursor_by_type, dict):
            parsed_cursors = {
                str(content_type_id): cursor
                for content_type_id, cursor in next_cursor_by_type.items()
                if isinstance(cursor, dict)
            }

        parsed_terminal = {}
        if isinstance(terminal_page_by_type, dict):
            parsed_terminal = {
                str(content_type_id): bool(value)
                for content_type_id, value in terminal_page_by_type.items()
            }

        return {
            "next_cursor_by_type": parsed_cursors,
            "terminal_page_by_type": parsed_terminal,
            "bootstrap_complete": bool(metadata.get("bootstrap_complete", False)),
        }
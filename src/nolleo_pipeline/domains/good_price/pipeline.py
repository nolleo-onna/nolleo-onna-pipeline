"""Good Price 도메인 동기화 오케스트레이션."""
from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

from nolleo_pipeline.common.http import build_http_client
from nolleo_pipeline.common.sync_logs import sync_log_run
from nolleo_pipeline.common.timezone import now_utc
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.good_price.client import OdcloudDatasetClient, PublicDataPageClient
from nolleo_pipeline.domains.good_price.models import ParsedFoodPlace
from nolleo_pipeline.domains.good_price.parser import (
    extract_items,
    parse_busan_food_row,
    parse_good_price_file_row,
    parse_good_price_menu_row,
    parse_good_price_store_row,
)
from nolleo_pipeline.domains.good_price.matcher import MAX_CANDIDATE_DISTANCE_M
from nolleo_pipeline.domains.good_price.repository import (
    FoodPlaceStoreEnrichRunResult,
    FoodSpotMatchRunResult,
    GoodPriceRepository,
    SpotPriceSummaryRefreshResult,
)

JOB_GOOD_PRICE_API = "good_price_store_sync"
JOB_GOOD_PRICE_MENU_API = "good_price_menu_sync"
JOB_GOOD_PRICE_FILE = "good_price_file_import"
JOB_GOOD_PRICE_ODCLOUD = "good_price_odcloud_sync"
JOB_BUSAN_FOOD_API = "busan_food_sync"
JOB_SPOT_PRICE_SUMMARY_REFRESH = "spot_price_summary_refresh"
JOB_FOOD_SPOT_MATCH = "food_spot_rule_match"
JOB_FOOD_PLACE_STORE_ENRICH = "food_place_store_enrich"

_BLOCK_PLACE_KEYWORDS = (
    "커트",
    "파마",
    "세탁",
    "미용",
    "헤어",
    "이발",
    "이미용",
    "숙박",
    "모텔",
    "호텔",
    "펜션",
)

_BLOCK_MENU_KEYWORDS = (
    "커트",
    "파마",
    "세탁",
)


async def run_good_price_shop_api_sync(
    *,
    max_pages: int | None = None,
    num_of_rows: int = 100,
) -> None:
    """이전 이름 호환용: 부산 착한가격업소 목록 API를 적재."""
    await run_good_price_store_api_sync(max_pages=max_pages, num_of_rows=num_of_rows)


async def run_good_price_store_api_sync(
    *,
    max_pages: int | None = None,
    num_of_rows: int = 100,
) -> None:
    """부산 착한가격업소 목록 API를 fd_food_* 테이블로 적재."""
    settings = get_settings()
    if not settings.busan_goodprice_api_key:
        raise ValueError("BUSAN_GOODPRICE_API_KEY is required")

    await _run_public_data_sync(
        job_name=JOB_GOOD_PRICE_API,
        endpoint_url=settings.busan_goodprice_store_api_url,
        service_key=settings.busan_goodprice_api_key,
        row_parser=parse_good_price_store_row,
        max_pages=max_pages,
        num_of_rows=num_of_rows,
    )


async def run_good_price_menu_api_sync(
    *,
    max_pages: int | None = None,
    num_of_rows: int = 100,
) -> None:
    """부산 착한가격업소 메뉴 API를 fd_food_* 테이블로 적재."""
    settings = get_settings()
    if not settings.busan_goodprice_api_key:
        raise ValueError("BUSAN_GOODPRICE_API_KEY is required")

    await _run_public_data_sync(
        job_name=JOB_GOOD_PRICE_MENU_API,
        endpoint_url=settings.busan_goodprice_menu_api_url,
        service_key=settings.busan_goodprice_api_key,
        row_parser=parse_good_price_menu_row,
        max_pages=max_pages,
        num_of_rows=num_of_rows,
    )


async def run_busan_food_api_sync(
    *,
    max_pages: int | None = None,
    num_of_rows: int = 100,
) -> None:
    """부산맛집정보 API를 fd_food_* 테이블로 적재."""
    settings = get_settings()
    service_key = settings.busan_food_api_key or settings.busan_goodprice_api_key
    if not service_key:
        raise ValueError("BUSAN_FOOD_API_KEY or BUSAN_GOODPRICE_API_KEY is required")

    await _run_public_data_sync(
        job_name=JOB_BUSAN_FOOD_API,
        endpoint_url=settings.busan_food_api_url,
        service_key=service_key,
        row_parser=parse_busan_food_row,
        max_pages=max_pages,
        num_of_rows=num_of_rows,
    )


async def run_good_price_odcloud_sync(
    *,
    endpoint_url: str,
    source_name: str,
    max_pages: int | None = None,
    per_page: int = 100,
) -> None:
    """odcloud 착한가격업소 데이터셋 API를 fd_food_* 테이블로 적재."""
    settings = get_settings()
    service_key = settings.busan_odcloud_api_key or settings.busan_goodprice_api_key
    if not service_key:
        raise ValueError("BUSAN_ODCLOUD_API_KEY or BUSAN_GOODPRICE_API_KEY is required")

    repo = GoodPriceRepository()
    async with sync_log_run(JOB_GOOD_PRICE_ODCLOUD, run_type="manual") as ctx:
        ctx.metadata["endpoint_url"] = endpoint_url
        ctx.metadata["source_name"] = source_name
        ctx.metadata["per_page"] = per_page
        async with build_http_client() as http:
            client = OdcloudDatasetClient(
                http,
                service_key=service_key,
                endpoint_url=endpoint_url,
            )
            page = 1
            while True:
                if max_pages is not None and page > max_pages:
                    break
                payload = await client.list_page(page=page, per_page=per_page)
                ctx.api_calls_used += 1
                fetched_at = now_utc()
                rows = extract_items(payload)
                if not rows:
                    break
                ctx.records_fetched += len(rows)
                for row in rows:
                    try:
                        parsed = parse_good_price_file_row(
                            row,
                            fetched_at=fetched_at,
                            source_file=source_name,
                        )
                        if _should_skip_by_keywords(parsed):
                            ctx.metadata.setdefault("skipped_keyword_count", 0)
                            ctx.metadata["skipped_keyword_count"] += 1
                            continue
                        await repo.upsert_place(parsed)
                        ctx.records_upserted += 1
                    except Exception as exc:  # noqa: BLE001
                        ctx.records_failed += 1
                        ctx.metadata.setdefault("errors", []).append(
                            {"page": page, "row": _row_label(row), "error": str(exc)[:300]}
                        )
                if len(rows) < per_page:
                    break
                page += 1
            ctx.metadata["last_page"] = page


async def run_food_place_store_enrich_sync(
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> FoodPlaceStoreEnrichRunResult:
    """good_price_store 메타데이터를 같은 이름의 good_price_menu row에 보강."""
    repo = GoodPriceRepository()
    async with sync_log_run(JOB_FOOD_PLACE_STORE_ENRICH, run_type="manual") as ctx:
        ctx.metadata["dry_run"] = dry_run
        ctx.metadata["limit"] = limit
        result = await repo.enrich_menu_places_from_store(dry_run=dry_run, limit=limit)
        ctx.records_fetched = result.menu_places_scanned
        ctx.records_upserted = result.enriched_count
        ctx.metadata["store_name_matches"] = result.store_name_matches
        ctx.metadata["address_filled"] = result.address_filled
        ctx.metadata["coords_filled"] = result.coords_filled
        ctx.metadata["tel_filled"] = result.tel_filled
        ctx.metadata["no_store_match"] = result.no_store_match
        return result


async def run_food_spot_match_sync(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    rematch_pending: bool = False,
    max_distance_m: float | None = None,
) -> FoodSpotMatchRunResult:
    """fd_food_places를 TourAPI 음식점 spots와 룰 매칭해 fd_food_place_spot_matches를 채운다."""
    repo = GoodPriceRepository()
    async with sync_log_run(JOB_FOOD_SPOT_MATCH, run_type="manual") as ctx:
        ctx.metadata["dry_run"] = dry_run
        ctx.metadata["limit"] = limit
        ctx.metadata["rematch_pending"] = rematch_pending
        resolved_max_distance_m = (
            max_distance_m if max_distance_m is not None else MAX_CANDIDATE_DISTANCE_M
        )
        ctx.metadata["max_distance_m"] = resolved_max_distance_m
        result = await repo.run_food_spot_rule_matching(
            dry_run=dry_run,
            limit=limit,
            rematch_pending=rematch_pending,
            max_distance_m=resolved_max_distance_m,
        )
        ctx.records_fetched = result.places_scanned
        ctx.records_upserted = result.matches_upserted
        ctx.metadata["places_scanned"] = result.places_scanned
        ctx.metadata["matched_count"] = result.matched_count
        ctx.metadata["pending_count"] = result.pending_count
        ctx.metadata["separate_count"] = result.separate_count
        ctx.metadata["no_candidate_count"] = result.no_candidate_count
        return result


async def refresh_spot_price_summary(
    *,
    dry_run: bool = False,
    prune_missing: bool = False,
) -> SpotPriceSummaryRefreshResult:
    """fd_food_* 현재 메뉴 가격을 sp_spot_price_summary 캐시로 재계산."""
    repo = GoodPriceRepository()
    async with sync_log_run(JOB_SPOT_PRICE_SUMMARY_REFRESH, run_type="manual") as ctx:
        ctx.metadata["dry_run"] = dry_run
        ctx.metadata["prune_missing"] = prune_missing
        result = await repo.refresh_spot_price_summary(
            dry_run=dry_run,
            prune_missing=prune_missing,
        )
        ctx.records_fetched = result.aggregated_count
        ctx.records_upserted = result.upserted_count
        ctx.metadata["aggregated_count"] = result.aggregated_count
        ctx.metadata["upserted_count"] = result.upserted_count
        ctx.metadata["pruned_count"] = result.pruned_count
        return result


async def _run_public_data_sync(
    *,
    job_name: str,
    endpoint_url: str,
    service_key: str,
    row_parser: Callable[..., ParsedFoodPlace],
    max_pages: int | None,
    num_of_rows: int,
) -> None:
    repo = GoodPriceRepository()
    async with sync_log_run(job_name, run_type="manual") as ctx:
        ctx.metadata["endpoint_url"] = endpoint_url
        ctx.metadata["num_of_rows"] = num_of_rows
        async with build_http_client() as http:
            client = PublicDataPageClient(
                http,
                service_key=service_key,
                endpoint_url=endpoint_url,
            )
            page = 1
            while True:
                if max_pages is not None and page > max_pages:
                    break
                payload = await client.list_page(page=page, num_of_rows=num_of_rows)
                ctx.api_calls_used += 1
                fetched_at = now_utc()
                rows = extract_items(payload)
                if not rows:
                    break
                ctx.records_fetched += len(rows)
                for row in rows:
                    try:
                        parsed = row_parser(row, fetched_at=fetched_at)
                        if _should_skip_by_keywords(parsed):
                            ctx.metadata.setdefault("skipped_keyword_count", 0)
                            ctx.metadata["skipped_keyword_count"] += 1
                            continue
                        await repo.upsert_place(parsed)
                        ctx.records_upserted += 1
                    except Exception as exc:  # noqa: BLE001
                        ctx.records_failed += 1
                        ctx.metadata.setdefault("errors", []).append(
                            {"page": page, "row": _row_label(row), "error": str(exc)[:300]}
                        )
                if len(rows) < num_of_rows:
                    break
                page += 1
            ctx.metadata["last_page"] = page


async def import_good_price_file(path: str | Path) -> None:
    """착한가격업소 CSV 파일을 fd_food_* 테이블로 적재."""
    source_path = Path(path)
    repo = GoodPriceRepository()
    async with sync_log_run(JOB_GOOD_PRICE_FILE, run_type="manual") as ctx:
        ctx.metadata["source_file"] = str(source_path)
        fetched_at = now_utc()
        with source_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row_number, row in enumerate(reader, start=2):
                ctx.records_fetched += 1
                try:
                    parsed = parse_good_price_file_row(
                        dict(row),
                        fetched_at=fetched_at,
                        source_file=str(source_path),
                    )
                    if _should_skip_by_keywords(parsed):
                        ctx.metadata.setdefault("skipped_keyword_count", 0)
                        ctx.metadata["skipped_keyword_count"] += 1
                        continue
                    await repo.upsert_place(parsed)
                    ctx.records_upserted += 1
                except Exception as exc:  # noqa: BLE001
                    ctx.records_failed += 1
                    ctx.metadata.setdefault("errors", []).append(
                        {"row_number": row_number, "row": _row_label(row), "error": str(exc)[:300]}
                    )


def _row_label(row: object) -> str:
    if not isinstance(row, dict):
        return repr(row)[:120]
    for key in ("idx", "IDX", "UC_SEQ", "bsshNm", "업소명", "상호명", "상호", "MAIN_TITLE", "name"):
        value = row.get(key)
        if value:
            return str(value)[:120]
    return repr(row)[:120]


def _contains_keyword(text: str | None, keywords: tuple[str, ...]) -> bool:
    if text is None:
        return False
    normalized = text.replace(" ", "")
    return any(keyword in normalized for keyword in keywords)


def _should_skip_by_keywords(parsed: ParsedFoodPlace) -> bool:
    place = parsed.place

    # 장소 자체가 비음식 카테고리/키워드면 전체 스킵.
    if _contains_keyword(place.name, _BLOCK_PLACE_KEYWORDS):
        return True
    if _contains_keyword(place.business_category, _BLOCK_PLACE_KEYWORDS):
        return True
    if _contains_keyword(place.representative_menu, _BLOCK_PLACE_KEYWORDS):
        return True

    # 메뉴명에 차단 키워드가 보이면 장소 전체를 스킵해
    # fd_food_places / fd_food_place_menus 모두 미적재로 유지.
    for menu in parsed.menus:
        if _contains_keyword(menu.menu_name, _BLOCK_MENU_KEYWORDS):
            return True
    return False

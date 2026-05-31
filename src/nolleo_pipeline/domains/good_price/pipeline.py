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
from nolleo_pipeline.domains.good_price.repository import GoodPriceRepository

JOB_GOOD_PRICE_API = "good_price_store_sync"
JOB_GOOD_PRICE_MENU_API = "good_price_menu_sync"
JOB_GOOD_PRICE_FILE = "good_price_file_import"
JOB_GOOD_PRICE_ODCLOUD = "good_price_odcloud_sync"
JOB_BUSAN_FOOD_API = "busan_food_sync"


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
    """부산 착한가격업소 목록 API를 food_* 테이블로 적재."""
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
    """부산 착한가격업소 메뉴 API를 food_* 테이블로 적재."""
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
    """부산맛집정보 API를 food_* 테이블로 적재."""
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
    """odcloud 착한가격업소 데이터셋 API를 food_* 테이블로 적재."""
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
    """착한가격업소 CSV 파일을 food_* 테이블로 적재."""
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

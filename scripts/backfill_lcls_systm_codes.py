# scripts/backfill_lcls_systm_codes.py
"""TourAPI KorService2 `lclsSystmCode2` → `lcls_systm_codes` 백필.

레포츠(28) 등 신규 contentType이 쓰는 (lclsSystm1,2,3) 조합이
`0009` 시드 시점의 spots_core에 없으면 FK `fk_spots_core_lcls`에 막힌다.
이 스크립트로 분류 마스터를 채운 뒤 spots sync를 재실행한다.

문서: docs/troubleshooting/lcls-systm-master-backfill.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from nolleo_pipeline.common.db import close_pool, get_pool
from nolleo_pipeline.common.http import build_http_client, get_json
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.spots.client import TOURAPI_BASE_URL, _raise_on_tourapi_error


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _parse_body_int(body: dict[str, Any], key: str) -> int | None:
    raw = body.get(key)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _triple_from_item(item: dict[str, Any]) -> tuple[str, str, str] | None:
    """TourAPI 응답 item → (code1, code2, code3). 필드명 변형을 허용."""
    candidates = (
        ("lclsSystm1", "lclsSystm2", "lclsSystm3"),
        ("lclsSystm1Cd", "lclsSystm2Cd", "lclsSystm3Cd"),
        ("code1", "code2", "code3"),
    )
    for k1, k2, k3 in candidates:
        c1 = _str(item.get(k1))
        c2 = _str(item.get(k2))
        c3 = _str(item.get(k3))
        if c1 and c2 and c3:
            return (c1, c2, c3)
    return None


def _name_from_item(item: dict[str, Any]) -> str:
    """표시용 이름. 소분류명 우선, 없으면 중·대 + pending."""
    for key in (
        "lclsSystm3Nm",
        "lclsSystmNm3",
        "lclsSystm2Nm",
        "lclsSystm1Nm",
        "lclsSystmNm",
        "name",
        "codeNm",
        "lclsSystmNm1",
    ):
        n = _str(item.get(key))
        if n:
            return n
    parts = [
        _str(item.get(k))
        for k in (
            "lclsSystm1Nm",
            "lclsSystm2Nm",
            "lclsSystm3Nm",
            "lclsSystmNm1",
            "lclsSystmNm2",
            "lclsSystmNm3",
        )
    ]
    parts = [p for p in parts if p]
    if parts:
        return " > ".join(parts)
    return "pending_sync"


async def _fetch_page(
    http: httpx.AsyncClient,
    *,
    service_key: str,
    lcls_systm1: str | None,
    page: int,
    num_of_rows: int,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "serviceKey": service_key,
        "MobileOS": "ETC",
        "MobileApp": "nolleo-onna",
        "_type": "json",
        "lclsSystmListYn": "Y",
        "numOfRows": str(num_of_rows),
        "pageNo": str(page),
    }
    if lcls_systm1:
        params["lclsSystm1"] = lcls_systm1
    url = f"{TOURAPI_BASE_URL}/lclsSystmCode2"
    payload = await get_json(http, url, params)
    _raise_on_tourapi_error(payload)
    return payload


async def main() -> None:
    parser = argparse.ArgumentParser(description="TourAPI lclsSystmCode2 → lcls_systm_codes")
    parser.add_argument(
        "--lcls-systm1",
        default="LS",
        help="대분류 코드 필터 (28 레포츠는 보통 LS). 빈 문자열이면 파라미터 생략.",
    )
    parser.add_argument("--num-of-rows", type=int, default=500, help="페이지당 행 수 (최대 1000 권장)")
    parser.add_argument("--max-pages", type=int, default=50, help="안전 상한 페이지 수")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB에 넣지 않고 첫 페이지 item 키·샘플만 출력",
    )
    args = parser.parse_args()

    settings = get_settings()
    lcls_filter: str | None = args.lcls_systm1 if args.lcls_systm1 else None

    rows: list[tuple[str, str, str, str]] = []

    async with build_http_client() as http:
        page = 1
        page_limit = args.max_pages
        while page <= page_limit:
            payload = await _fetch_page(
                http,
                service_key=settings.tour_api_key,
                lcls_systm1=lcls_filter,
                page=page,
                num_of_rows=args.num_of_rows,
            )
            body = payload.get("response", {}).get("body", {})
            if not isinstance(body, dict):
                raise ValueError("unexpected response: missing response.body")

            items_page = _extract_list_items(payload)

            if page == 1 and args.dry_run and items_page:
                print("first item keys:", sorted(items_page[0].keys()))
                print("first item sample:", json.dumps(items_page[0], ensure_ascii=False)[:800])

            if page == 1:
                total_count = _parse_body_int(body, "totalCount")
                num_of_rows_resp = _parse_body_int(body, "numOfRows") or args.num_of_rows
                if total_count is not None and num_of_rows_resp > 0:
                    needed = max(1, (total_count + num_of_rows_resp - 1) // num_of_rows_resp)
                    page_limit = min(args.max_pages, needed)

            if not items_page:
                break

            for item in items_page:
                triple = _triple_from_item(item)
                if triple is None:
                    continue
                name = _name_from_item(item)
                rows.append((*triple, name))

            page += 1

    # 중복 제거 (code1,2,3)
    dedup: dict[tuple[str, str, str], str] = {}
    for c1, c2, c3, name in rows:
        key = (c1, c2, c3)
        if key not in dedup or dedup[key] == "pending_sync":
            dedup[key] = name

    print(f"parsed {len(rows)} rows from API, {len(dedup)} distinct (code1,code2,code3)")

    if args.dry_run:
        print("dry-run: skipping DB write")
        return

    if not dedup:
        print("nothing to insert — check --dry-run and TourAPI field names")
        return

    pool = await get_pool()
    insert_sql = """
        INSERT INTO lcls_systm_codes (code1, code2, code3, name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (code1, code2, code3) DO NOTHING
    """
    async with pool.connection() as conn, conn.transaction():
        params_list = [(c1, c2, c3, name) for (c1, c2, c3), name in dedup.items()]
        for params in params_list:
            await conn.execute(insert_sql, params)

    print("insert completed (ON CONFLICT DO NOTHING — 기존 행은 유지)")


async def _async_main() -> None:
    try:
        await main()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_async_main())

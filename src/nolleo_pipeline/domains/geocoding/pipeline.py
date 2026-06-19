"""Geocoding 도메인 동기화 오케스트레이션."""
from __future__ import annotations

import asyncio

from nolleo_pipeline.common.http import build_http_client
from nolleo_pipeline.common.sync_logs import sync_log_run
from nolleo_pipeline.config import get_settings
from nolleo_pipeline.domains.geocoding.client import KakaoGeocodingClient
from nolleo_pipeline.domains.geocoding.models import (
    FoodPlaceGeocodeRunResult,
    FoodPlaceInferenceRunResult,
    FoodPlaceInferenceTarget,
    GeocodeResult,
)
from nolleo_pipeline.domains.geocoding.parser import (
    address_looks_like_busan,
    build_keyword_search_queries,
    is_in_busan,
    normalize_address_for_geocode,
    parse_kakao_keyword_response,
)
from nolleo_pipeline.domains.geocoding.repository import GeocodingRepository
from nolleo_pipeline.llm.place_address import (
    AUTO_APPLY_LLM_CONFIDENCE,
    infer_place_address,
)

JOB_FOOD_PLACE_GEOCODE = "food_place_geocode"
JOB_FOOD_PLACE_ADDRESS_INFERENCE = "food_place_address_inference"
GEOCODE_REQUEST_INTERVAL_SECONDS = 0.12


async def run_food_place_geocode_sync(
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> FoodPlaceGeocodeRunResult:
    """주소가 있는 fd_food_places에 Kakao 지오코딩으로 좌표를 보강."""
    settings = get_settings()
    if not settings.kakao_rest_api_key:
        raise ValueError("KAKAO_REST_API_KEY is required")

    repo = GeocodingRepository()
    places = await repo.list_food_places_missing_coordinates(limit=limit)
    geocoded_count = 0
    failed_count = 0
    skipped_no_address = 0

    async with sync_log_run(JOB_FOOD_PLACE_GEOCODE, run_type="manual") as ctx:
        ctx.metadata["dry_run"] = dry_run
        ctx.metadata["limit"] = limit
        ctx.metadata["provider"] = "kakao"
        ctx.records_fetched = len(places)

        async with build_http_client() as http:
            client = KakaoGeocodingClient(http, api_key=settings.kakao_rest_api_key)
            for place in places:
                query = normalize_address_for_geocode(place.address)
                if query is None:
                    skipped_no_address += 1
                    continue

                try:
                    result = await client.geocode_address(query)
                    ctx.api_calls_used += 1
                except Exception as exc:  # noqa: BLE001
                    failed_count += 1
                    ctx.records_failed += 1
                    ctx.metadata.setdefault("errors", []).append(
                        {
                            "food_place_id": place.food_place_id,
                            "name": place.name[:120],
                            "address": place.address[:200],
                            "error": str(exc)[:300],
                        }
                    )
                    await asyncio.sleep(GEOCODE_REQUEST_INTERVAL_SECONDS)
                    continue

                if result is None:
                    failed_count += 1
                    ctx.records_failed += 1
                    ctx.metadata.setdefault("unresolved_addresses", []).append(
                        {
                            "food_place_id": place.food_place_id,
                            "name": place.name[:120],
                            "query": query[:200],
                        }
                    )
                    await asyncio.sleep(GEOCODE_REQUEST_INTERVAL_SECONDS)
                    continue

                geocoded_count += 1
                if not dry_run:
                    await repo.update_food_place_coordinates(place.food_place_id, result)
                    ctx.records_upserted += 1

                await asyncio.sleep(GEOCODE_REQUEST_INTERVAL_SECONDS)

        ctx.metadata["geocoded_count"] = geocoded_count
        ctx.metadata["failed_count"] = failed_count
        ctx.metadata["skipped_no_address"] = skipped_no_address

    return FoodPlaceGeocodeRunResult(
        places_scanned=len(places),
        geocoded_count=geocoded_count,
        failed_count=failed_count,
        skipped_no_address=skipped_no_address,
        dry_run=dry_run,
    )


async def _resolve_via_keyword(
    client: KakaoGeocodingClient,
    place: FoodPlaceInferenceTarget,
) -> tuple[GeocodeResult | None, int]:
    api_calls = 0
    for query in build_keyword_search_queries(
        name=place.name,
        source_region=place.source_region,
    ):
        payload = await client.search_keyword(query)
        api_calls += 1
        result = parse_kakao_keyword_response(
            payload,
            query=query,
            place_name=place.name,
            place_tel=place.tel,
        )
        if result is not None:
            return result, api_calls
    return None, api_calls


async def _resolve_via_llm_address(
    client: KakaoGeocodingClient,
    *,
    place: FoodPlaceInferenceTarget,
    openai_api_key: str,
    openai_llm_model: str,
) -> tuple[GeocodeResult | None, float | None]:
    inference = await infer_place_address(
        api_key=openai_api_key,
        model_name=openai_llm_model,
        name=place.name,
        source_region=place.source_region,
        tel=place.tel,
        representative_menu=place.representative_menu,
        menu_names=place.menu_names,
    )
    if inference is None:
        return None, None
    if inference.confidence < AUTO_APPLY_LLM_CONFIDENCE:
        return None, inference.confidence
    if not address_looks_like_busan(inference.address):
        return None, inference.confidence

    query = normalize_address_for_geocode(inference.address)
    if query is None:
        return None, inference.confidence

    result = await client.geocode_address(query)
    if result is None or not is_in_busan(result.map_x, result.map_y):
        return None, inference.confidence

    return (
        GeocodeResult(
            map_x=result.map_x,
            map_y=result.map_y,
            normalized_query=query,
            resolved_address=inference.address,
            method="llm_address",
        ),
        inference.confidence,
    )


async def run_food_place_address_inference_sync(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    skip_llm: bool = False,
) -> FoodPlaceInferenceRunResult:
    """주소 없는 fd_food_places에 Kakao 키워드 + LLM 주소 추론으로 좌표를 보강."""
    settings = get_settings()
    if not settings.kakao_rest_api_key:
        raise ValueError("KAKAO_REST_API_KEY is required")

    repo = GeocodingRepository()
    places = await repo.list_food_places_missing_location(limit=limit)
    resolved_count = 0
    keyword_resolved_count = 0
    llm_resolved_count = 0
    failed_count = 0
    skipped_low_confidence = 0
    use_llm = not skip_llm and bool(settings.openai_api_key)

    async with sync_log_run(JOB_FOOD_PLACE_ADDRESS_INFERENCE, run_type="manual") as ctx:
        ctx.metadata["dry_run"] = dry_run
        ctx.metadata["limit"] = limit
        ctx.metadata["skip_llm"] = skip_llm
        ctx.metadata["use_llm"] = use_llm
        ctx.records_fetched = len(places)

        async with build_http_client() as http:
            client = KakaoGeocodingClient(http, api_key=settings.kakao_rest_api_key)
            for place in places:
                resolved: GeocodeResult | None = None
                method = None
                low_confidence_hit = False

                try:
                    resolved, keyword_calls = await _resolve_via_keyword(client, place)
                    ctx.api_calls_used += keyword_calls
                    if resolved is not None:
                        method = "keyword"
                    elif use_llm:
                        resolved, llm_confidence = await _resolve_via_llm_address(
                            client,
                            place=place,
                            openai_api_key=settings.openai_api_key,
                            openai_llm_model=settings.openai_llm_model,
                        )
                        ctx.api_calls_used += 2
                        if resolved is None and llm_confidence is not None:
                            low_confidence_hit = True
                            skipped_low_confidence += 1
                            ctx.metadata.setdefault("low_confidence", []).append(
                                {
                                    "food_place_id": place.food_place_id,
                                    "name": place.name[:120],
                                    "confidence": llm_confidence,
                                }
                            )
                        elif resolved is not None:
                            method = "llm_address"
                except Exception as exc:  # noqa: BLE001
                    failed_count += 1
                    ctx.records_failed += 1
                    ctx.metadata.setdefault("errors", []).append(
                        {
                            "food_place_id": place.food_place_id,
                            "name": place.name[:120],
                            "error": str(exc)[:300],
                        }
                    )
                    await asyncio.sleep(GEOCODE_REQUEST_INTERVAL_SECONDS)
                    continue

                if resolved is None:
                    if not low_confidence_hit:
                        failed_count += 1
                    ctx.metadata.setdefault("unresolved_places", []).append(
                        {
                            "food_place_id": place.food_place_id,
                            "name": place.name[:120],
                        }
                    )
                    await asyncio.sleep(GEOCODE_REQUEST_INTERVAL_SECONDS)
                    continue

                resolved_count += 1
                if method == "keyword":
                    keyword_resolved_count += 1
                elif method == "llm_address":
                    llm_resolved_count += 1

                address = resolved.resolved_address or resolved.normalized_query
                if not dry_run:
                    await repo.update_food_place_location(
                        place.food_place_id,
                        address=address,
                        result=resolved,
                    )
                    ctx.records_upserted += 1

                await asyncio.sleep(GEOCODE_REQUEST_INTERVAL_SECONDS)

        ctx.metadata["resolved_count"] = resolved_count
        ctx.metadata["keyword_resolved_count"] = keyword_resolved_count
        ctx.metadata["llm_resolved_count"] = llm_resolved_count
        ctx.metadata["failed_count"] = failed_count
        ctx.metadata["skipped_low_confidence"] = skipped_low_confidence

    return FoodPlaceInferenceRunResult(
        places_scanned=len(places),
        resolved_count=resolved_count,
        keyword_resolved_count=keyword_resolved_count,
        llm_resolved_count=llm_resolved_count,
        failed_count=failed_count,
        skipped_low_confidence=skipped_low_confidence,
        dry_run=dry_run,
    )

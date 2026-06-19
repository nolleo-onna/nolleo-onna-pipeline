from __future__ import annotations

from nolleo_pipeline.domains.good_price.repository import (
    SPOT_DETAILS_TABLE,
    SPOT_PRICE_SUMMARY_AGGREGATE_SQL,
    SPOT_PRICE_SUMMARY_TABLE,
    SPOTS_TABLE,
    SpotPriceMenuCandidate,
    build_spot_price_summary_records,
)


def test_representative_menu_prefers_explicit_representative() -> None:
    summaries = build_spot_price_summary_records(
        [
            _candidate(menu_name="김밥", price=5000, display_order=1),
            _candidate(
                menu_name="대표국밥",
                price=8000,
                display_order=2,
                is_representative=True,
            ),
        ]
    )

    assert summaries[0].representative_menu_name == "대표국밥"
    assert summaries[0].representative_price == 8000


def test_representative_menu_falls_back_to_cheapest_then_display_order_and_name() -> None:
    summaries = build_spot_price_summary_records(
        [
            _candidate(menu_name="비빔밥", price=7000, display_order=2),
            _candidate(menu_name="국수", price=6000, display_order=2),
            _candidate(menu_name="라면", price=6000, display_order=1),
        ]
    )

    assert summaries[0].representative_menu_name == "라면"
    assert summaries[0].representative_price == 6000


def test_min_avg_menu_count_and_source_count_are_calculated() -> None:
    summaries = build_spot_price_summary_records(
        [
            _candidate(food_place_id=1, menu_name="김밥", price=5000),
            _candidate(food_place_id=1, menu_name="라면", price=6000),
            _candidate(food_place_id=2, menu_name="국밥", price=8500),
        ]
    )

    assert len(summaries) == 1
    assert summaries[0].min_price == 5000
    assert summaries[0].avg_price == 6500
    assert summaries[0].menu_count == 3
    assert summaries[0].source_count == 2


def test_menus_without_positive_price_are_excluded() -> None:
    summaries = build_spot_price_summary_records(
        [
            _candidate(menu_name="가격없음", price=None),
            _candidate(menu_name="무료표기오류", price=0),
            _candidate(menu_name="정상메뉴", price=7000),
        ]
    )

    assert summaries[0].menu_count == 1
    assert summaries[0].min_price == 7000
    assert summaries[0].representative_menu_name == "정상메뉴"


def test_unmatched_separate_and_rejected_matches_are_excluded() -> None:
    summaries = build_spot_price_summary_records(
        [
            _candidate(menu_name="정상메뉴", price=7000, match_status="matched"),
            _candidate(menu_name="대기메뉴", price=1000, match_status="pending"),
            _candidate(menu_name="분리메뉴", price=2000, match_status="separate"),
            _candidate(menu_name="거절메뉴", price=3000, match_status="rejected"),
            _candidate(menu_name="스팟없음", price=4000, spot_content_id=None),
        ]
    )

    assert summaries[0].menu_count == 1
    assert summaries[0].representative_menu_name == "정상메뉴"


def test_sql_targets_backend_prefixed_summary_table() -> None:
    assert SPOT_PRICE_SUMMARY_TABLE == "sp_spot_price_summary"
    assert SPOTS_TABLE == "sp_spots"
    assert SPOT_DETAILS_TABLE == "sp_spot_details"
    assert "fd_food_place_spot_matches" in SPOT_PRICE_SUMMARY_AGGREGATE_SQL
    assert "fd_food_place_menus" in SPOT_PRICE_SUMMARY_AGGREGATE_SQL
    assert "matches.match_status = 'matched'" in SPOT_PRICE_SUMMARY_AGGREGATE_SQL


def _candidate(
    *,
    spot_content_id: str | None = "spot-1",
    food_place_id: int = 1,
    menu_name: str,
    price: int | None,
    source: str = "good_price_file",
    is_representative: bool = False,
    display_order: int | None = 1,
    match_status: str = "matched",
) -> SpotPriceMenuCandidate:
    return SpotPriceMenuCandidate(
        spot_content_id=spot_content_id,
        food_place_id=food_place_id,
        menu_name=menu_name,
        price=price,
        source=source,
        is_representative=is_representative,
        display_order=display_order,
        match_status=match_status,
    )

from __future__ import annotations

from nolleo_pipeline.common.timezone import now_utc
from nolleo_pipeline.domains.good_price.parser import (
    extract_items,
    parse_busan_food_row,
    parse_good_price_file_row,
    parse_good_price_menu_row,
    parse_good_price_shop_row,
    parse_good_price_store_row,
)


def test_extract_items_from_public_data_shape() -> None:
    payload = {"response": {"body": {"items": {"item": [{"idx": "1"}, {"idx": "2"}]}}}}

    assert extract_items(payload) == [{"idx": "1"}, {"idx": "2"}]


def test_parse_good_price_file_row_unpivots_menu_columns() -> None:
    parsed = parse_good_price_file_row(
        {
            "시군": "해운대구",
            "업종": "한식",
            "업소명": "온나식당",
            "연락처": "051-123-4567",
            "주소": "부산 해운대구 A로 1",
            "품목1": "김치찌개",
            "가격1": "7,000원",
            "품목2": "된장찌개",
            "가격2": "6500",
        },
        fetched_at=now_utc(),
        source_file="good_price.csv",
    )

    assert parsed.place.name == "온나식당"
    assert parsed.place.normalized_category == "food_korean"
    assert parsed.place.is_course_food_candidate is True
    assert parsed.source.source == "good_price_file"
    assert parsed.source.external_id
    assert [(menu.menu_name, menu.price) for menu in parsed.menus] == [
        ("김치찌개", 7000),
        ("된장찌개", 6500),
    ]


def test_parse_good_price_shop_row_keeps_external_id() -> None:
    parsed = parse_good_price_shop_row(
        {
            "idx": "123",
            "sj": "착한국밥",
            "cn": "기타요식업",
            "adres": "부산 중구 B로 2",
            "tel": "051 000 1111",
            "parkngAt": "Y",
        },
        fetched_at=now_utc(),
    )

    assert parsed.source.source == "good_price_store"
    assert parsed.source.external_id == "123"
    assert parsed.place.name == "착한국밥"
    assert parsed.place.parking_available is True
    assert parsed.place.tel == "0510001111"


def test_parse_good_price_menu_api_row_maps_single_menu_price() -> None:
    parsed = parse_good_price_menu_row(
        {
            "bsshNm": "오곡흑미쌀짜장",
            "itemNm": "자장면",
            "menuPrc": 6000,
            "crtDt": "20251211",
        },
        fetched_at=now_utc(),
    )

    assert parsed.place.name == "오곡흑미쌀짜장"
    assert parsed.source.source == "good_price_menu"
    assert parsed.source.external_id == "bsshNm:오곡흑미쌀짜장"
    assert [(menu.menu_name, menu.price) for menu in parsed.menus] == [("자장면", 6000)]


def test_parse_good_price_menu_api_groups_same_store_by_name() -> None:
    fetched_at = now_utc()
    jjajang = parse_good_price_menu_row(
        {"bsshNm": "오곡흑미쌀짜장", "itemNm": "자장면", "menuPrc": 6000},
        fetched_at=fetched_at,
    )
    jjambbong = parse_good_price_menu_row(
        {"bsshNm": "오곡흑미쌀짜장", "itemNm": "짬뽕", "menuPrc": 8000},
        fetched_at=fetched_at,
    )

    assert jjajang.source.external_id == jjambbong.source.external_id


def test_parse_good_price_store_row_maps_store_api_without_menu() -> None:
    parsed = parse_good_price_store_row(
        {
            "idx": "4553",
            "sj": "대가호",
            "adres": "(49341) 부산광역시 사하구 낙동대로250번안길 2",
            "tel": "051-205-8252",
            "cn": "음식점",
            "locale": "괴정 1동",
            "intrcn": "저렴한가격, 질좋은 재료",
            "parkngAt": "Y",
            "bsnTime": "10:00~20:30",
        },
        fetched_at=now_utc(),
    )

    assert parsed.source.source == "good_price_store"
    assert parsed.source.external_id == "4553"
    assert parsed.place.name == "대가호"
    assert parsed.place.source_region == "괴정 1동"
    assert parsed.place.parking_available is True
    assert parsed.menus == []


def test_parse_good_price_file_row_accepts_gu_specific_headers() -> None:
    parsed = parse_good_price_file_row(
        {
            "연번": "1",
            "업종": "한식",
            "상호": "북구식당",
            "사업장 주소": "부산광역시 북구 A로 1",
            "주차가능여부": "가능",
            "배달가능여부": "N",
        },
        fetched_at=now_utc(),
        source_file="북구_착한가격업소.csv",
    )

    assert parsed.place.name == "북구식당"
    assert parsed.place.address == "부산광역시 북구 A로 1"
    assert parsed.place.parking_available is True
    assert parsed.place.delivery_available is False


def test_parse_busan_food_row_maps_api_fields() -> None:
    parsed = parse_busan_food_row(
        {
            "UC_SEQ": "69",
            "MAIN_TITLE": "로스포르쪼",
            "GUGUN_NM": "영도구",
            "LAT": "35.08712",
            "LNG": "128.90971",
            "ADDR1": "강서구 명지오션시티7로 29",
            "CNTCT_TEL": "051-205-7406",
            "USAGE_DAY_WEEK_AND_TIME": "11:00a.m. ~ 22:00p.m.",
            "RPRSNTV_MENU": "생면 파스타",
            "ITEMCNTNTS": "창밖의 풍경이 아름다운 곳",
        },
        fetched_at=now_utc(),
    )

    assert parsed.source.source == "busan_food"
    assert parsed.source.external_id == "69"
    assert parsed.place.name == "로스포르쪼"
    assert parsed.place.source_region == "영도구"
    assert parsed.place.map_x == 128.90971
    assert parsed.place.map_y == 35.08712
    assert parsed.place.representative_menu == "생면 파스타"

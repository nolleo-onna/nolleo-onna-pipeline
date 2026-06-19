from __future__ import annotations

from nolleo_pipeline.domains.good_price.matcher import (
    AUTO_MATCH_THRESHOLD,
    FoodPlaceMatchCandidate,
    PENDING_THRESHOLD,
    SpotMatchCandidate,
    apply_ambiguity_penalty,
    compute_match_score,
    decide_match_status,
    jaro_winkler_similarity,
    normalize_match_address,
    normalize_match_name,
    normalize_match_phone,
    pick_best_match,
    tel_match_score,
)


def _food_place(
    *,
    food_place_id: int = 1,
    name: str = "온나식당",
    tel: str | None = "051-123-4567",
    address: str | None = "부산 해운대구 해운대로 1",
    map_x: float | None = 129.16,
    map_y: float | None = 35.16,
) -> FoodPlaceMatchCandidate:
    return FoodPlaceMatchCandidate(
        food_place_id=food_place_id,
        name=name,
        tel=tel,
        address=address,
        map_x=map_x,
        map_y=map_y,
    )


def _spot(
    *,
    spot_content_id: str = "spot-1",
    title: str = "온나식당",
    tel: str | None = "0511234567",
    address: str | None = "부산광역시 해운대구 해운대로 1",
    distance_m: float | None = 12.0,
) -> SpotMatchCandidate:
    return SpotMatchCandidate(
        spot_content_id=spot_content_id,
        title=title,
        tel=tel,
        address=address,
        distance_m=distance_m,
    )


def test_normalize_match_phone_strips_non_digits() -> None:
    assert normalize_match_phone("051-123-4567") == "0511234567"


def test_jaro_winkler_similarity_is_high_for_similar_names() -> None:
    score = jaro_winkler_similarity("해운대해수욕장", "해운대 해수욕장")
    assert score >= 0.9


def test_tel_match_score_requires_same_digits() -> None:
    assert tel_match_score("051-123-4567", "0511234567") == 1.0
    assert tel_match_score("051-123-4567", "051-999-9999") == 0.0


def test_tel_match_score_accepts_matching_local_number_suffix() -> None:
    assert tel_match_score("051-1234-5678", "12345678") == 1.0


def test_normalize_match_name_strips_branch_suffix() -> None:
    assert normalize_match_name("예반(광안점)") == "예반"


def test_normalize_match_address_unifies_region_label() -> None:
    left = normalize_match_address("부산 해운대구 해운대로 1")
    right = normalize_match_address("부산광역시 해운대구 해운대로 1")
    assert left == right


def test_apply_ambiguity_penalty_downgrades_close_second_place() -> None:
    assert apply_ambiguity_penalty("matched", best_score=0.9, second_best_score=0.87) == "pending"
    assert apply_ambiguity_penalty("pending", best_score=0.7, second_best_score=0.68) == "separate"
    assert apply_ambiguity_penalty("matched", best_score=0.9, second_best_score=0.8) == "matched"


def test_decide_match_status_uses_thresholds() -> None:
    assert decide_match_status(AUTO_MATCH_THRESHOLD) == "matched"
    assert decide_match_status(PENDING_THRESHOLD) == "pending"
    assert decide_match_status(PENDING_THRESHOLD - 0.01) == "separate"


def test_compute_match_score_prefers_phone_and_name_match() -> None:
    score = compute_match_score(_food_place(), _spot())
    assert score >= AUTO_MATCH_THRESHOLD


def test_pick_best_match_selects_highest_scoring_spot() -> None:
    best = pick_best_match(
        _food_place(name="온나식당"),
        [
            _spot(spot_content_id="weak", title="다른식당", tel=None, distance_m=180.0),
            _spot(spot_content_id="strong", title="온나식당", tel="0511234567", distance_m=10.0),
        ],
    )

    assert best is not None
    assert best.spot_content_id == "strong"
    assert best.match_status == "matched"


def test_pick_best_match_downgrades_ambiguous_auto_match() -> None:
    best = pick_best_match(
        _food_place(name="온나식당", tel="051-123-4567"),
        [
            _spot(spot_content_id="a", title="온나식당", tel="0511234567", distance_m=10.0),
            _spot(spot_content_id="b", title="온나식당본점", tel="0511234567", distance_m=12.0),
        ],
    )

    assert best is not None
    assert best.spot_content_id == "a"
    assert best.match_status == "pending"


def test_pick_best_match_returns_separate_when_scores_are_low() -> None:
    best = pick_best_match(
        _food_place(name="온나식당"),
        [
            _spot(
                spot_content_id="far",
                title="완전다른가게",
                tel="0510000000",
                address="부산 중구",
                distance_m=190.0,
            )
        ],
    )

    assert best is not None
    assert best.match_status == "separate"

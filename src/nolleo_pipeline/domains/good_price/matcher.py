"""fd_food_places ↔ spots 룰 기반 매칭."""
from __future__ import annotations

import re
from dataclasses import dataclass

MATCH_METHOD_RULE = "rule"

AUTO_MATCH_THRESHOLD = 0.85
PENDING_THRESHOLD = 0.65

WEIGHT_TEL = 0.5
WEIGHT_NAME = 0.3
WEIGHT_ADDRESS = 0.15
WEIGHT_DISTANCE = 0.05

MAX_CANDIDATE_DISTANCE_M = 200.0
AMBIGUITY_SCORE_GAP = 0.08
MIN_NAME_SCORE_FOR_MATCHED_WITHOUT_TEL = 0.95


@dataclass(frozen=True)
class FoodPlaceMatchCandidate:
    """매칭 대상 음식 장소."""

    food_place_id: int
    name: str
    tel: str | None
    address: str | None
    map_x: float | None
    map_y: float | None


@dataclass(frozen=True)
class SpotMatchCandidate:
    """매칭 후보 TourAPI 스팟."""

    spot_content_id: str
    title: str
    tel: str | None
    address: str | None
    distance_m: float | None


@dataclass(frozen=True)
class ScoredSpotMatch:
    """점수가 계산된 매칭 후보."""

    spot_content_id: str | None
    match_score: float
    match_status: str


_ADDRESS_REGION_ALIASES: tuple[tuple[str, str], ...] = (
    ("서울특별시", "서울"),
    ("부산광역시", "부산"),
    ("대구광역시", "대구"),
    ("인천광역시", "인천"),
    ("광주광역시", "광주"),
    ("대전광역시", "대전"),
    ("울산광역시", "울산"),
    ("세종특별자치시", "세종"),
    ("경기도", "경기"),
    ("강원특별자치도", "강원"),
    ("강원도", "강원"),
    ("충청북도", "충북"),
    ("충청남도", "충남"),
    ("전북특별자치도", "전북"),
    ("전라북도", "전북"),
    ("전라남도", "전남"),
    ("경상북도", "경북"),
    ("경상남도", "경남"),
    ("제주특별자치도", "제주"),
    ("제주도", "제주"),
)


def normalize_match_text(value: str | None) -> str:
    """이름/주소 비교용 공백 제거."""
    if value is None:
        return ""
    return re.sub(r"\s+", "", value.strip())


def normalize_match_name(value: str | None) -> str:
    """지점명·괄호·기호를 제거한 상호 비교용 문자열."""
    if value is None:
        return ""
    text = value.strip()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"[^\w가-힣]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "", text)


def normalize_match_address(value: str | None) -> str:
    """행정구역 표기를 통일한 주소 비교용 문자열."""
    if value is None:
        return ""
    text = " ".join(value.split())
    for source, target in _ADDRESS_REGION_ALIASES:
        text = text.replace(source, target)
    return re.sub(r"\s+", "", text)


def normalize_match_phone(value: str | None) -> str:
    """전화번호 비교용 숫자만 남김."""
    if value is None:
        return ""
    return re.sub(r"\D+", "", value)


def jaro_winkler_similarity(left: str, right: str) -> float:
    """0~1 문자열 유사도."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0

    left_len = len(left)
    right_len = len(right)
    match_distance = max(left_len, right_len) // 2 - 1
    left_matches = [False] * left_len
    right_matches = [False] * right_len

    matches = 0
    transpositions = 0
    for index in range(left_len):
        start = max(0, index - match_distance)
        end = min(index + match_distance + 1, right_len)
        for right_index in range(start, end):
            if right_matches[right_index] or left[index] != right[right_index]:
                continue
            left_matches[index] = True
            right_matches[right_index] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    left_pos = 0
    right_pos = 0
    while left_pos < left_len and right_pos < right_len:
        if not left_matches[left_pos]:
            left_pos += 1
            continue
        if not right_matches[right_pos]:
            right_pos += 1
            continue
        if left[left_pos] != right[right_pos]:
            transpositions += 1
        left_pos += 1
        right_pos += 1

    jaro = (
        matches / left_len
        + matches / right_len
        + (matches - transpositions / 2) / matches
    ) / 3.0

    prefix = 0
    for left_char, right_char in zip(left, right, strict=False):
        if left_char != right_char:
            break
        prefix += 1
        if prefix == 4:
            break

    return min(1.0, jaro + prefix * 0.1 * (1 - jaro))


def distance_score(distance_m: float | None, *, max_distance_m: float = MAX_CANDIDATE_DISTANCE_M) -> float:
    """가까울수록 1에 가까운 거리 점수."""
    if distance_m is None:
        return 0.0
    if distance_m >= max_distance_m:
        return 0.0
    return max(0.0, 1.0 - distance_m / max_distance_m)


def tel_match_score(food_tel: str | None, spot_tel: str | None) -> float:
    """전화번호 일치 여부."""
    left = normalize_match_phone(food_tel)
    right = normalize_match_phone(spot_tel)
    if len(left) < 7 or len(right) < 7:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 8 and len(right) >= 8 and left[-8:] == right[-8:]:
        return 1.0
    return 0.0


def compute_match_score(
    food_place: FoodPlaceMatchCandidate,
    spot: SpotMatchCandidate,
) -> float:
    """ADR 0001 가중치로 최종 매칭 점수를 계산."""
    name_score = jaro_winkler_similarity(
        normalize_match_name(food_place.name),
        normalize_match_name(spot.title),
    )
    address_score = jaro_winkler_similarity(
        normalize_match_address(food_place.address),
        normalize_match_address(spot.address),
    )
    return round(
        tel_match_score(food_place.tel, spot.tel) * WEIGHT_TEL
        + name_score * WEIGHT_NAME
        + address_score * WEIGHT_ADDRESS
        + distance_score(spot.distance_m) * WEIGHT_DISTANCE,
        3,
    )


def has_strong_match_evidence(
    food_place: FoodPlaceMatchCandidate,
    spot: SpotMatchCandidate,
) -> bool:
    """자동 matched에 필요한 강한 근거(전화 일치 또는 매우 높은 상호 유사도)."""
    if tel_match_score(food_place.tel, spot.tel) > 0.0:
        return True
    name_score = jaro_winkler_similarity(
        normalize_match_name(food_place.name),
        normalize_match_name(spot.title),
    )
    return name_score >= MIN_NAME_SCORE_FOR_MATCHED_WITHOUT_TEL


def apply_ambiguity_penalty(
    match_status: str,
    *,
    best_score: float,
    second_best_score: float | None,
) -> str:
    """1·2위 점수 차가 작으면 자동 확정을 한 단계 낮춘다."""
    if second_best_score is None:
        return match_status
    if best_score - second_best_score >= AMBIGUITY_SCORE_GAP:
        return match_status
    if match_status == "matched":
        return "pending"
    if match_status == "pending":
        return "separate"
    return match_status


def finalize_match_status(
    food_place: FoodPlaceMatchCandidate,
    spot: SpotMatchCandidate,
    *,
    match_score: float,
    second_best_score: float | None,
) -> str:
    """점수·근거·모호성을 반영해 최종 match_status를 결정."""
    match_status = decide_match_status(match_score)
    if match_status == "matched" and not has_strong_match_evidence(food_place, spot):
        match_status = "pending"
    return apply_ambiguity_penalty(
        match_status,
        best_score=match_score,
        second_best_score=second_best_score,
    )


def pick_best_match(
    food_place: FoodPlaceMatchCandidate,
    spots: list[SpotMatchCandidate],
) -> ScoredSpotMatch | None:
    """후보 중 최고 점수 매칭을 선택."""
    if not spots:
        return None

    scored: list[tuple[SpotMatchCandidate, float]] = []
    for spot in spots:
        scored.append((spot, compute_match_score(food_place, spot)))

    scored.sort(key=lambda item: item[1], reverse=True)
    best_spot, best_score = scored[0]
    second_best_score = scored[1][1] if len(scored) > 1 else None

    return ScoredSpotMatch(
        spot_content_id=best_spot.spot_content_id,
        match_score=best_score,
        match_status=finalize_match_status(
            food_place,
            best_spot,
            match_score=best_score,
            second_best_score=second_best_score,
        ),
    )


def decide_match_status(score: float) -> str:
    """점수 구간별 match_status 결정."""
    if score >= AUTO_MATCH_THRESHOLD:
        return "matched"
    if score >= PENDING_THRESHOLD:
        return "pending"
    return "separate"

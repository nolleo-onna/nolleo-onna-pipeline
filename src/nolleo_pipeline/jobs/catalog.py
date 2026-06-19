"""잡 카탈로그 — 모든 잡을 한 곳에서 레지스트리에 등록한다.

[이 파일이 왜 있냐]
- scripts/run_*.py 에 흩어져 있던 "어떤 잡이 있나"를 단일 카탈로그로 모은다.
- CLI(`nolleo list/run`)와 스케줄러가 이 파일을 import 하면 모든 잡이 등록된다.
- 도메인 모듈에 데코레이터를 박지 않고 여기서 명시 등록 → 도메인은 import-light 유지,
  잡 목록은 이 파일만 보면 한눈에 파악.

[추가 방법]
- 도메인의 run_*_sync 를 import 하고 register(JobSpec(...)) 한 줄 추가.
- JobSpec.name 은 반드시 해당 잡의 sync_log_run(job_name) 과 일치시킬 것.
- CLI 플래그는 잡 시그니처에서 자동 도출되므로 여기서 따로 선언하지 않는다.
"""

from __future__ import annotations

from nolleo_pipeline.common.jobs import JobSpec, register
from nolleo_pipeline.domains.congestion.pipeline import (
    run_congestion_old_purge,
    run_today_concentration_cache_refresh,
    run_tourapi_congestion_sync,
)
from nolleo_pipeline.domains.geocoding.pipeline import (
    run_food_place_address_inference_sync,
    run_food_place_geocode_sync,
)
from nolleo_pipeline.domains.good_price.pipeline import (
    import_good_price_file,
    refresh_spot_price_summary,
    run_busan_food_api_sync,
    run_food_place_store_enrich_sync,
    run_food_spot_match_sync,
    run_good_price_menu_api_sync,
    run_good_price_odcloud_sync,
    run_good_price_store_api_sync,
)
from nolleo_pipeline.domains.spots.pipeline import run_tourapi_spots_sync
from nolleo_pipeline.domains.travel_courses.pipeline import (
    run_tourapi_travel_courses_sync,
)

_JOBS = (
    # ── TourAPI 수집 ──
    JobSpec(
        name="tourapi_courses_sync",
        fn=run_tourapi_travel_courses_sync,
        description="부산 여행코스(contentTypeId=25) 동기화",
    ),
    JobSpec(
        name="tourapi_spots_sync",
        fn=run_tourapi_spots_sync,
        description="부산 관광지/문화/레포츠/음식(12·14·28·39) 동기화",
    ),
    JobSpec(
        name="tourapi_congestion_sync",
        fn=run_tourapi_congestion_sync,
        description="부산 시군구 혼잡도 예측 일일 동기화",
    ),
    JobSpec(
        name="today_concentration_cache_refresh",
        fn=run_today_concentration_cache_refresh,
        description="SPOTS 오늘자 혼잡도 캐시 갱신 (가드 4종)",
    ),
    JobSpec(
        name="congestion_old_purge",
        fn=run_congestion_old_purge,
        description="7일 이전 혼잡도 row 정리",
    ),
    # ── 음식/착한가격 수집 ──
    JobSpec(
        name="good_price_store_sync",
        fn=run_good_price_store_api_sync,
        description="부산 착한가격업소 목록 API 적재",
    ),
    JobSpec(
        name="good_price_menu_sync",
        fn=run_good_price_menu_api_sync,
        description="부산 착한가격업소 메뉴 API 적재",
    ),
    JobSpec(
        name="busan_food_sync",
        fn=run_busan_food_api_sync,
        description="부산맛집정보 API 적재",
    ),
    JobSpec(
        name="good_price_odcloud_sync",
        fn=run_good_price_odcloud_sync,
        description="odcloud 착한가격 데이터셋 적재 (--endpoint-url, --source-name 필수)",
    ),
    JobSpec(
        name="good_price_file_import",
        fn=import_good_price_file,
        description="착한가격 CSV 파일 적재 (--path 필수)",
    ),
    # ── 음식 후처리 (보강/매칭/캐시) ──
    JobSpec(
        name="food_place_store_enrich",
        fn=run_food_place_store_enrich_sync,
        description="store 메타데이터를 menu row에 보강",
    ),
    JobSpec(
        name="food_spot_rule_match",
        fn=run_food_spot_match_sync,
        description="음식 장소 ↔ TourAPI 음식 spot 룰 매칭",
    ),
    JobSpec(
        name="spot_price_summary_refresh",
        fn=refresh_spot_price_summary,
        description="sp_spot_price_summary 가격 캐시 재계산",
    ),
    # ── 지오코딩 ──
    JobSpec(
        name="food_place_geocode",
        fn=run_food_place_geocode_sync,
        description="주소 있는 음식 장소에 Kakao 좌표 보강",
    ),
    JobSpec(
        name="food_place_address_inference",
        fn=run_food_place_address_inference_sync,
        description="주소 없는 음식 장소에 Kakao 키워드 + LLM 주소 추론",
    ),
)

for _spec in _JOBS:
    register(_spec)

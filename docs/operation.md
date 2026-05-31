# 놀러온나 운영 정책 문서

이 문서는 현재 Alembic 리셋 체인(`0001` → `0008`) 기준 운영 정책입니다.
과거 문서의 `SPOTS_CORE`, `GOOD_PRICE_*`, `SPOT_CONGESTION_FORECAST` 중심 설계는
legacy 설계 기록이며 현재 DB에는 반영되어 있지 않습니다.

## 1. 현재 마이그레이션 체인

| Revision | 내용 |
| --- | --- |
| `0001` | `public`, `vectors` 스키마, `postgis`, `pg_trgm`, `vector`, `set_updated_at()` |
| `0002` | 소셜 로그인용 `users` |
| `0003` | `spots`, `spot_details`, `spots_raw_snapshots`, `spot_images` |
| `0004` | 공식 여행코스 `travel_courses`, `travel_course_raw_snapshots`, `course_items` |
| `0005` | 생성 코스 `generated_courses`, `generated_course_items`, `course_decisions` |
| `0006` | 파이프라인 `sync_logs` |
| `0007` | 음식/가격 공통 도메인 `food_*`, `spot_price_summary` |
| `0008` | 부산 `ldong_codes` |

## 2. 외부 데이터 매핑

| 원천 | 대표 키 | RAW/원천 보존 | 정규화 대상 |
| --- | --- | --- | --- |
| TourAPI 관광지 12/14/28/39 | `contentid` | `spots_raw_snapshots.raw_json` | `spots`, `spot_details`, `spot_images` |
| TourAPI 공식 여행코스 25 | `contentid` | `travel_course_raw_snapshots.raw_json` | `travel_courses`, `course_items` |
| 착한가격업소 API/파일 | 원천별 `external_id` | `food_place_sources.raw_json` | `food_places`, `food_place_menus`, `food_price_observations` |
| RedTable/부산맛집/모범음식점 등 | 원천별 `external_id` | `food_place_sources.raw_json` | `food_places`, `food_place_menus`, `food_price_observations` |
| 운영자 수기 가격 | 내부 place/menu | `food_price_observations.raw_payload` | 승인 후 `food_place_menus` 반영 |

## 3. ID와 네이밍 원칙

- TourAPI `contentid`는 내부 ID가 아니라 원천 자연키입니다.
- `spots.content_id`, `generated_course_items.spot_content_id`,
  `course_decisions.spot_content_id`, `course_decisions.replacement_spot_id`는
  모두 `VARCHAR(20)` 기준을 유지합니다.
- 앱 내부 생성/수정/삭제 감사 컬럼은 `created_at`, `created_by`, `updated_at`,
  `updated_by`, `deleted_at`, `deleted_by`를 씁니다.
- 원천 생성/수정 시각은 `source_created_at`, `source_modified_time`,
  `fetched_at`, `synced_at`처럼 명확히 분리합니다.
- `spots_core`는 현재 스키마에서 사용하지 않습니다. 스팟 마스터는 `spots`입니다.

## 4. 저장 방식

### UPSERT

- `users`: `(provider, external_id)`
- `spots`: `content_id`
- `spot_details`: `content_id`
- `spots_raw_snapshots`: `content_id`
- `travel_courses`: `content_id`
- `travel_course_raw_snapshots`: `content_id`
- `generated_courses`: 내부 `id` 중심, 공유 토큰은 partial unique
- `food_place_sources`: `(source, external_id)`
- `food_place_menus`: `(food_place_id, menu_name, source)`
- `sync_logs`: append 후 종료 시 update

### REPLACE

- `spot_images`: 스팟 단위로 기존 이미지 삭제 후 새 이미지 삽입
- `course_items`: 공식 여행코스 단위로 기존 아이템 삭제 후 새 아이템 삽입

### APPEND / 이력

- `food_price_observations`: 가격 관측/검수 이력
- `course_decisions`: 코스 추천 의사결정 로그
- `sync_logs`: 파이프라인 실행 이력

## 5. 스팟 도메인

`spots`는 TourAPI 관광지/문화시설/레포츠/음식점의 핵심 마스터입니다.

- `content_type_id`: MVP 기준 `12`, `14`, `28`, `39`
- 좌표는 `map_x`, `map_y`로 보관하고 `geog` generated column을 둡니다.
- `spot_details`는 연락처, 주소, 소개, intro JSONB 같은 cold 데이터를 보관합니다.
- `spots_raw_snapshots`는 endpoint별 원천 응답을 JSONB로 보존합니다.
- `spot_images`는 `detailImage2` 결과를 1:N으로 보관합니다.
- TourAPI에서 사라진 row는 hard delete하지 않고 `is_active=false`,
  `inactive_since`로 비활성화합니다.

비활성화는 안전 가드 통과 시에만 수행합니다.

- 전체 대상 contentTypeId가 마지막 페이지까지 도달
- API 예산 중단 없음
- 실패율이 `SPOTS_DEACTIVATE_MAX_FAILURE_RATE` 미만
- 비활성 후보 비율이 `SPOTS_DEACTIVATE_MAX_RATIO` 미만

## 6. 공식 여행코스 도메인

`travel_courses`는 TourAPI 공식 여행코스(`contentTypeId=25`) 마스터입니다.
사용자가 추천받아 저장한 코스는 `generated_courses`에 저장합니다.

- `travel_courses.content_id`: 공식 코스 contentid
- `travel_course_raw_snapshots`: 원천 응답 최신본
- `course_items`: 공식 코스 하위 방문지
- `course_items.matched_spot_id`: `spots.content_id` 매칭 성공 시만 입력, nullable
- `course_items.sub_*`: 매칭 실패 시 UI fallback용 원문

`course_items`는 코스 단위 REPLACE를 사용합니다.

## 7. 생성 코스 도메인

`generated_courses`는 사용자가 추천받고 저장/공유하는 생성 코스입니다.

- `user_id`: 저장 사용자
- `parent_course_id`: 재추천/복제 원본
- `compared_with_travel_course_id`: 공식 여행코스와 비교할 때 참조
- `generated_course_items.spot_content_id`: 방문 스팟 `spots.content_id`
- `course_decisions.decision_type`: `exclude`, `replace`, `boost`
- `course_decisions.severity`: `critical`, `warning`, `info`

## 8. 음식/가격 도메인

가격 정보는 `spots`에 직접 넣지 않고 `food_places` 도메인으로 관리합니다.
TourAPI 음식점(`contentTypeId=39`)과 가격/메뉴 원천은 품질과 식별자가 다르기 때문입니다.

### food_places

외부 음식/가격 장소 마스터입니다.

- 업소명, 업종 원문, 표준 카테고리, 주소, 전화번호, 영업시간 원문
- 대표 메뉴, 배달/주차 여부, 좌표, 활성 상태
- `is_course_food_candidate`로 코스 식사 후보 여부를 구분

### food_place_sources

원천별 식별자와 원본 payload를 보존합니다.

허용 source:

- `good_price_shop`
- `good_price_menu`
- `good_price_file`
- `redtable`
- `busan_food`
- `model_restaurant`
- `admin_manual`

### food_place_menus

서비스 조회용 현재 메뉴/가격입니다.

- source of truth 중 하나지만, 관측 이력은 `food_price_observations`에 남깁니다.
- `(food_place_id, menu_name, source)` 기준으로 현재값을 유지합니다.
- CSV의 `품목1/가격1`, `품목2/가격2` 같은 wide format은 메뉴 row로 펼쳐 저장합니다.

### food_price_observations

가격 관측/검수 이력입니다.

- `source_type`: `api`, `file_import`, `admin_manual`, `user_report`, `crawler`
- `review_status`: `pending`, `approved`, `rejected`
- 승인된 관측만 현재 메뉴 가격 반영 대상으로 봅니다.

### food_place_spot_matches

`food_places`와 TourAPI `spots`의 매칭 테이블입니다.

- `pending`, `matched`, `rejected`는 `spot_content_id IS NOT NULL`
- `separate`는 `spot_content_id IS NULL`
- 이 규칙은 CHECK constraint로 강제합니다.

### spot_price_summary

추천 조회 최적화용 캐시입니다.

- source of truth가 아닙니다.
- `food_place_menus`, `food_price_observations`를 기준으로 재계산할 수 있어야 합니다.
- 스팟 기준 최저가, 평균가, 대표 메뉴 가격, 메뉴 수, source 수를 저장합니다.

## 9. 지역 코드

`ldong_codes`는 현재 부산 16개 시군구만 seed합니다.

- `regn_cd='26'`
- `signgu_cd`: 3자리 법정동 시군구 코드

TourAPI 혼잡도 같은 일부 API가 `26110`처럼 시도+시군구 결합 코드를 요구해도,
내부 표준은 3자리 `signgu_cd`를 유지하고 API 호출 시점에만 결합합니다.

## 10. sync_logs 운영

모든 파이프라인 잡은 `sync_logs`에 시작/종료/메트릭을 남깁니다.

- `job_name`: 잡 이름
- `run_type`: `scheduled`, `manual`, `triggered`, `regression`
- `status`: `running`, `success`, `failed`, `partial`, `cancelled`
- `metadata`: 커서, skip reason, 오류 샘플, 비활성화 메트릭 등 job별 확장 정보

부분 실패는 가능하면 잡 전체 실패로 올리지 않고 `metadata.errors[]`에 샘플을 기록합니다.

## 11. 후속 도메인

현재 마이그레이션에 포함되지 않은 항목은 후속 브랜치에서 별도 설계합니다.

- 혼잡도 forecast/cache
- 스팟/코스/사용자 임베딩
- 행사 도메인
- 북마크/리뷰/방문 이력
- 날씨/대기질 캐시

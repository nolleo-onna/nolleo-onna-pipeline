# 놀러온나 — 운영 정책 문서

> 테이블별 상세 운영 정책 + API 적재표 + 저장 방식 + 대표 쿼리 + 인덱스 초안 + 데이터 흐름 매트릭스
> DDL/파이프라인 작성 시 진실의 원천(SoT)으로 참조해야 할 문서

---

## 1. API 적재표

### 외부 API/운영 입력 → 정규화 테이블 매핑


| #   | API 이름                               | 대표 키                       | RAW 저장 테이블              | 정규화 테이블 (적재 순서)                                                                         | 비고                                                 |
| --- | ------------------------------------ | -------------------------- | ----------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------- |
| 1   | TourAPI 관광지 (ContentTypeId 12/14/39) | `content_id`               | `SPOTS_RAW_SNAPSHOTS`   | `SPOTS_CORE` → `SPOT_DETAILS` → `SPOT_IMAGES` → (LLM) → `SPOT_TAGS` + `SPOT_EMBEDDINGS` | 4개 endpoint 통합 (detailCommon2/Intro2/Info2/Image2) |
| 2   | TourAPI 행사 (ContentTypeId 15)        | `content_id`               | `EVENTS_RAW_SNAPSHOTS`  | `EVENTS_CORE` → `EVENT_DETAILS` → `EVENT_IMAGES` → (LLM) → `EVENT_EMBEDDINGS`           | searchFestival2 + detail*                          |
| 3   | TourAPI 여행코스 (ContentTypeId 25)      | `content_id`               | `COURSES_RAW_SNAPSHOTS` | `TRAVEL_COURSES` → `COURSE_ITEMS` → (LLM) → `TRAVEL_COURSE_EMBEDDINGS`                  | detailInfo2의 하위 스팟 1:N                             |
| 4   | TourAPI 혼잡도 (TatsCnctrRateService)   | `(tAtsNm, baseYmd)`        | (RAW 미보관)               | `SPOT_CONGESTION_FORECAST`                                                              | content_id 매칭 시도, 실패 시 NULL                        |
| 5   | 부산 착한가격업소 (getMulgaInfoList)         | `idx`                      | `GPS_RAW_SNAPSHOTS`     | `GOOD_PRICE_SHOPS` → `GOOD_PRICE_MATCH_QUEUE`                                           | XML → JSONB 변환                                     |
| 6   | 카카오 지오코딩                             | (주소)                       | (RAW 미보관)               | `GOOD_PRICE_SHOPS.map_x/y` UPDATE                                                       | 좌표 보충용, 실패 시 `geocode_failed=true`                 |
| 7   | 기상청 단기예보                             | `(signgu_cd, observed_at)` | (RAW 미보관)               | `WEATHER_CACHE`                                                                         | TTL 15분, 시군구 16개 격자                                |
| 8   | 운영자 수기 가격 입력                           | `(shop_id, item_name)`     | (RAW 미보관)               | `GOOD_PRICE_PRICE_OBSERVATIONS(approved)` → `GOOD_PRICE_SHOP_PRICES`                    | 초기 MVP 핵심, 크롤링 없이 운영                           |
| 9   | 사용자 가격 제보                              | `observation_id`           | (RAW 미보관)               | `GOOD_PRICE_PRICE_OBSERVATIONS(pending→approved/rejected)` → `GOOD_PRICE_SHOP_PRICES`   | 증빙 기반 검수 후 반영                                  |


### LLM/임베딩 파생 산출물


| #   | 산출물             | 트리거                | 적재 테이블                                                                                                  |
| --- | --------------- | ------------------ | ------------------------------------------------------------------------------------------------------- |
| L1  | overview LLM 요약 | `overview_hash` 변경 | `SPOTS_CORE.overview_summary`, `EVENTS_CORE.overview_summary`, `TRAVEL_COURSES.overview_summary`        |
| L2  | 영업시간 LLM 정규화    | intro/bsnTime 변경   | `BUSINESS_HOURS_REVIEW_QUEUE` → `SPOT_DETAILS.business_hours`, `GOOD_PRICE_SHOPS.business_hours_parsed` |
| L3  | 태그 LLM 추출       | overview/title 변경  | `SPOT_TAGS` (TAGS 마스터 매핑 후)                                                                             |
| L4  | 임베딩 생성          | source_text 변경     | `SPOT_EMBEDDINGS`, `EVENT_EMBEDDINGS`, `TRAVEL_COURSE_EMBEDDINGS`, `USER_EMBEDDINGS`, `TAGS.embedding`  |


---

## 2. 테이블별 저장 방식

### UPSERT (동일 ID면 갱신)

```
SPOTS_CORE              -- content_id PK
SPOT_DETAILS            -- content_id PK
SPOT_EMBEDDINGS         -- content_id PK
EVENTS_CORE
EVENT_DETAILS
EVENT_EMBEDDINGS
TRAVEL_COURSES
TRAVEL_COURSE_EMBEDDINGS
GOOD_PRICE_SHOPS        -- external_id UK
GOOD_PRICE_SHOP_PRICES  -- (shop_id, item_name) UK
TAGS                    -- tag_name UK
USERS                   -- (provider, external_id) UK
USER_EMBEDDINGS         -- user_id PK
VISIT_HISTORY           -- (user_id, spot_content_id) UK
BOOKMARK_COLLECTIONS    -- (user_id, collection_type) 시스템 폴더만
WEATHER_CACHE           -- (signgu_cd, observed_at) UK
SPOT_CONGESTION_FORECAST -- partial UK 2종 (matched / unmatched 분리)
```

### REPLACE (DELETE-then-INSERT, 부모 단위 통째 교체)

```
SPOT_IMAGES             -- 스팟별 갤러리 통째 교체
EVENT_IMAGES            -- 행사별 갤러리 통째 교체
COURSE_ITEMS            -- 코스별 하위 스팟 통째 교체
SPOT_TAGS (source='llm'만)  -- LLM 재추출 시, manual은 보존
HANKKUT_SPOTS, HANKKUT_TAGS, HANKKUT_EVENTS  -- N:M join
```

### APPEND ONLY (이력/시계열, INSERT 만)

```
USER_REVIEWS            -- 시계열, soft delete만
NOTIFICATIONS           -- 시계열
GENERATED_COURSES       -- 사용자 생성 이력
GENERATED_COURSE_ITEMS  -- 코스의 부속
COURSE_DECISIONS        -- 의사결정 로그
BUSINESS_HOURS_REVIEW_QUEUE  -- 검수 큐
GOOD_PRICE_MATCH_QUEUE  -- 매칭 큐
GOOD_PRICE_PRICE_OBSERVATIONS -- 가격 관측/수기 입력 이력
SYNC_LOGS               -- 운영 로그
BOOKMARKS               -- 사용자 북마크 (hard delete 정책)
```

### RAW SNAPSHOTS (UPSERT, 최신만 보관)

```
SPOTS_RAW_SNAPSHOTS     -- content_id PK
EVENTS_RAW_SNAPSHOTS
COURSES_RAW_SNAPSHOTS
GPS_RAW_SNAPSHOTS       -- shop_id PK
```

*MVP는 이력 미보관 (단순화). 1주일 이상 사라졌다 재등장하는 케이스에서 raw 손실 가능.*

---

## 3. 도메인별 상세 운영 정책

### 👤 사용자 도메인

#### USERS

- **인증**: 카카오/네이버/구글 OAuth (`(provider, external_id)` 복합 UK)
- **익명 사용자 미운영** (소셜 로그인 진입장벽 낮음)
- **role**: 'user' / 'admin'
- **soft delete**: `deleted_at` 30일 유예 후 hard delete
- **last_active_at**: 5분 throttle 갱신 (매 요청마다 UPDATE 회피)
- **탈퇴 처리**:
  - 본인 데이터 (BOOKMARKS, VISIT_HISTORY, USER_EMBEDDINGS): 카스케이드 삭제
  - 공개 데이터 (USER_REVIEWS): `user_id` SET NULL로 익명화 보존
- **확장성**: 단일 테이블로 100만 유저까지 충분, 파티셔닝 불필요

#### USER_EMBEDDINGS

- **목적**: "내 취향 코스 추천"의 데이터 기반
- **계산 가중치**: 방문(VISIT_HISTORY) > 고평점 리뷰(rating ≥ 4) > 북마크 > 가보고싶음 폴더 순
- **콜드 스타트**: 활동 5건 미만 → row 미생성, "내 취향" 옵션 비활성화
- **갱신**: 일 1회 새벽 배치 (매번 갱신 회피)
- **모델 변경**: SYNC_LOGS에 `user_embedding_recompute` job 등록 → 전체 재계산
- **비용**: text-embedding-3-small 기준 사용자당 ~$0.0001, MAU 5,000 × 일 1회 = ~$0.5/일

#### REFRESH_TOKENS (테이블 없음, Redis 운영)

- 토큰 검증 = 매 API 요청 핫패스 → DB 부적합
- Redis 키 구조:
  - `refresh_token:{hash}` → `{user_id, user_agent, ip, last_used_at}` (TTL 14~30일)
  - `user:{id}:tokens` Set → 사용자별 활성 세션 관리

#### BOOKMARKS

- **다형성 회피**: 4개 FK 컬럼 (`spot_content_id`, `generated_course_id`, `event_content_id`, `hankkut_id`) 중 정확히 1개 NOT NULL CHECK
- **부분 UK 4개**: `(user_id, target_id) WHERE target_id IS NOT NULL` 부분 UK로 중복 방지
- **collection_id NOT NULL**: 모든 북마크는 폴더 소속 강제
- **hard delete 정책**: 다시 북마크 시 새 row 생성, `created_at` 갱신
- **사용자당 1만 개 상한**: 악성 폭주 방지
- **비활성 대상 필터링**: SPOTS_CORE/EVENTS_CORE의 `is_active=false` 대상은 조회 시 LEFT JOIN으로 필터

#### BOOKMARK_COLLECTIONS

- **collection_type**: `default`(저장됨) / `wishlist`(가보고싶음) / `custom`
- **시스템 폴더**: 가입 시 `default`, `wishlist` 자동 생성, 1유저당 1개 보장 (부분 UK)
- **bookmark_count**: 정당한 비정규화 (폴더 목록 핫패스), 애플리케이션 증감 + 주 1회 cron 보정
- **사용자 폴더 100개 상한**

#### VISIT_HISTORY

- **목적**: 사용자 실제 방문 이력 (개인화 추천 강한 신호)
- **(user_id, spot_content_id) UK** + `visit_count` 누적 + 메모 갱신
- **with_companion**: 코스 입력값과 매칭, 개인화 핵심 신호
- **upsert 트리거**: 리뷰 작성 시 자동 (`visit_count++`, `last_visited_at = KST today`)

#### USER_REVIEWS

- **(user_id, spot_content_id) UK**: 1유저 1스팟 1리뷰 (deleted_at IS NULL 부분)
- **content 500자 제한**, **rating 1~5 CHECK**
- **soft delete 30일 후 hard delete cron**
- **리뷰 변경 시**: `SPOTS_CORE.avg_rating/review_count` 동기 갱신 + 일 1회 cron 보정 (드리프트 방지)
- **Rate Limit**: 1유저 시간당 5리뷰
- **부적절 리뷰**: 관리자 직접 삭제 (신고 시스템 미채택)

#### NOTIFICATIONS

- **type enum**: `course_saved` / `event_upcoming` / `spot_closed_today` / `hankkut_approved`
- **MVP는 인앱 전용** (푸시·이메일 미구현)
- **보존 90일** 후 cron hard delete
- **사용자당 100건 상한** (오래된 것부터 삭제)

---

### 🗺️ 코스 도메인

#### GENERATED_COURSES

- **사용자 생성 코스 전용** (운영자 큐레이션은 TRAVEL_COURSES)
- **user_id NOT NULL** (익명 사용자 미운영)
- **weight_profile**: `balanced` / `budget_focused`
- **generation_method**: `natural`(AI 자연어) / `form`(5조건) / `recommend`(내 취향)
- **pair_id**: 같은 입력으로 가격 가중치 다른 형제 코스 2개 묶음
- **share_token UK**: 공유 URL 직접 접근, 비로그인 열람 OK
- **Rate Limit**: 1유저 시간당 5회 (LLM 비용 보호)
- **view_count throttling**: 1유저 1코스 1시간 1증가
- **soft delete**: 사용자 삭제 시 30일 후 hard delete, 공유 URL은 "삭제된 코스" 표시
- **"공식 코스 짠내 변환"**: TRAVEL_COURSES → COURSE_ITEMS 가성비 대체 → 새 GENERATED_COURSES 생성 + `compared_with_travel_course_id` 기록 → `total_savings` 계산

#### GENERATED_COURSE_ITEMS

- **(course_id, serial_num) UK**: 순서 중복 방지
- 코스 편집 = row 단위 INSERT/UPDATE/DELETE (배열 통째 UPDATE 회피)

#### COURSE_DECISIONS ⭐

- **차별점 핵심**: "왜 이 코스인지" 의사결정 로그
- **decision_type**: `exclude` / `replace` / `boost`
- **severity**: `critical` / `warning` / `info`
- **evidence JSONB 표준 스키마 (공통 계약)**:
  ```json
  {
    "schema_version": "v1",
    "weather": {
      "pty": 1,
      "sky_condition": 4,
      "temp_c": 22.3,
      "reason": "비 예보로 실외 체류 위험"
    },
    "congestion": {
      "level": 4,
      "rate": 73.2,
      "base_ymd": "2026-05-03"
    },
    "business_hours_check": {
      "checked_at": "2026-05-03T11:20:00+09:00",
      "is_open_now": false,
      "next_open_at": "2026-05-03T17:00:00+09:00"
    },
    "price": {
      "source": "good_price_price_observations",
      "observation_id": 12345,
      "expected_cost": 9000
    },
    "festival": {
      "event_content_id": "EVT123",
      "impact": "nearby_traffic_high"
    },
    "notes": ["우천 시 실내 대체", "혼잡 회피 우선"]
  }
  ```
- **필수 키**: `schema_version`, `business_hours_check`
- **호환성 규칙**: 새 필드 추가는 허용, 기존 필드 의미 변경은 `schema_version` 상승 후 적용
- **UI 노출**: 코스 상세 화면 상단 "왜 이 코스인가요" 띠

---

### 📰 콘텐츠 도메인 (한끗)

#### HANKKUT

- **목적**: 플랜 B 보강 데이터 (비 오는 날 대안·반나절·혼자 등 상황별 큐레이션)
- **MVP는 관리자 전용 작성** (`author_user_id` = `role='admin'` 검증)
- **status**: `pending` / `approved` / `rejected` / `archived`
- **source**: `manual` / `auto_event`
- **자동 한끗 cron**: 매일 새벽 다가올 7일 행사 → `pending` 한끗 자동 생성 (`source='auto_event'`)
- **시즌 종료 자동 archive**: 매일 새벽 `valid_until < CURRENT_DATE AND status='approved'` → `archived`
- **content 3000자 제한 CHECK**

#### HANKKUT_SPOTS / HANKKUT_TAGS / HANKKUT_EVENTS

- **N:M 매핑** (단일 FK 컬럼 회피, 일원화)
- **HANKKUT_EVENTS 대표 행사 정책 (SSOT)**:
  - "대표 행사 = `display_order = 1`" 명문화
  - 모든 조회는 공통 쿼리/뷰로 통일
  - `HANKKUT.related_event_id` 같은 별도 컬럼 미도입 (동기화 문제 차단)
  - 서비스 레이어 단일화: `attachHankkutEvents(hankkutId, events[])` 함수 강제 경유

#### BUSINESS_HOURS_REVIEW_QUEUE ⭐

- **차별점 핵심**: LLM 할루시네이션 차단 파이프라인
- **다층 검증**: `confidence` + 룰 검증 + 원문 재구성 검증 → `validation_passed`
- **추적성**: `model_name`, `model_version`, `prompt_version`, `source_text_hash`
- **임계값 3단계**:
  - `confidence ≥ 0.85` + `validation_passed=true` → 자동 적용 (큐 미진입)
  - `0.7 ~ 0.85` → 큐잉 + 24h SLA + UI "검증 중"
  - `< 0.7` 또는 `validation_passed=false` → 큐잉 + UI "확인 필요"
- **parsed_json 표준 스키마** (시간은 KST):
  ```json
  {
    "weekly": {"mon": [{"open": "09:00", "close": "22:00"}], "wed": "closed"},
    "breaks": [{"start": "15:00", "end": "17:00"}],
    "holidays": ["매주 월요일", "공휴일"],
    "notes": "라스트 오더 21:30"
  }
  ```
- **회귀 테스트**: 모델/프롬프트 변경 시 100건 정답 셋 재돌림, 95% 일치 시에만 배포
- **처리 완료 row 30일 보관 후 hard delete**

---

### 📍 스팟 도메인

#### SPOTS_CORE (Hot)

- **서비스 전체 핫패스**: 코스 생성·지도·검색에서 가장 자주 조회
- **geog generated column**:
  ```sql
  geog geography(POINT, 4326) GENERATED ALWAYS AS
    (ST_SetSRID(ST_MakePoint(map_x, map_y), 4326)::geography) STORED
  ```
- **영업시간 SoT**: `SPOT_DETAILS.business_hours` JSONB 단일화
- **영업중 판정**: `is_open_now()` stored function (캐시 컬럼 미도입)
- **함수 호출 정책**:
  - **금지**: 단독 사용 (`WHERE is_open_now(content_id)` 만) → 풀스캔
  - **올바름**: 인덱스 선행 필터 결합 (`l_dong_signgu_cd`, `is_active`, `ST_DWithin`)
- **캐시 컬럼**:
  - `today_concentration_rate`: 매일 새벽 SPOT_CONGESTION_FORECAST에서 캐시
  - `avg_rating`/`review_count`: USER_REVIEWS 변경 시 동기 + 일 1회 cron 보정
  - `is_good_price`: GOOD_PRICE_SHOPS.matched_spot_id 변경 시 동기
- **비활성 처리**: TourAPI에서 사라지면 `is_active=false` + `inactive_since=NOW()` (hard delete X)
- **확장 트리거 (전국)**: 활성 5만 row 또는 `is_open_now()` p95 > 500ms 1주 지속 시 캐시 도입 검토

#### SPOT_DETAILS (Cold)

- **business_hours_source 전이**:
  - `tourapi_raw` → TourAPI 원본 (정규화 전)
  - `llm_auto` → LLM 자동 (confidence ≥ 0.85)
  - `llm_verified` → 관리자 검수 통과
  - `manual` → 관리자 직접 입력
- **overview_hash 활용**: TourAPI sync 시 비교 → 변경 시 (1) summary 재생성 (2) embedding 재계산 (3) intro에서 영업시간 추출 → BHR_QUEUE 재큐잉
- **stale_after**: `parsed_at + 90일` → UI에 "정보 갱신 필요" 배지

#### SPOT_EMBEDDINGS

- **모델**: text-embedding-3-small (1536 dim)
- **source_text 구조**: `{title}\n태그: {tags}\n{overview_summary}`
- **재임베딩 트리거**: `overview_hash` 변경 / `SPOT_TAGS` 변경 / `title` 변경
- **모델 변경**: SYNC_LOGS에 `embedding_full_recompute` job 등록 → 일괄 재계산
- **차원 다른 모델 변경**: 컬럼 타입 자체 교체 + 병행 운영 → 검증 → 구 컬럼 제거
- **비용**: 부산 전체 ~$28/회, 일일 변경 ~$1.4
- **하이브리드 검색**: 키워드 (pg_trgm GIN) + 의미 (HNSW) → RRF 점수 합산

#### SPOTS_RAW_SNAPSHOTS

- **JSONB 표준 구조**:
  ```json
  {
    "endpoints": {
      "detailCommon2": { "data": {...}, "fetched_at": "..." },
      "detailIntro2":  { "data": {...}, "fetched_at": "..." },
      "detailInfo2":   { "data": {...}, "fetched_at": "..." },
      "detailImage2":  { "data": {...}, "fetched_at": "..." }
    }
  }
  ```
- **이력 미보관** (MVP 단순화), 최신만 UPSERT
- 파싱 버그 시 raw → 재파싱 → CORE/DETAILS UPDATE
- 부산 ~140MB (평균 20KB × 7,000 row)

#### SPOT_IMAGES

- **(content_id, serial_num) UK**
- **TourAPI CDN URL 직접 참조** (자체 호스팅 X)
- **sync 시 DELETE-then-INSERT** (단순화)
- 매일 새벽 샘플링 cron으로 HEAD 요청 URL 검증, 실패율 5% 초과 시 알림

#### SPOT_CONGESTION_FORECAST ⭐

- **차별점 핵심**: "줄 서다 끝남" 실패 방지
- **content_id nullable**: TourAPI 매칭 실패 케이스 (공식 인정)
- **UPSERT UK (NULL 갭 방지)**:
  - `content_id IS NOT NULL` → `(content_id, base_ymd, source)` partial UK로 upsert
  - `content_id IS NULL` → `(raw_tats_name, signgu_cd, base_ymd, source)` partial UK로 upsert
  - 이유: PostgreSQL UNIQUE는 `NULL`을 distinct로 취급하므로, 미매칭 row 중복 적재를 별도 키로 차단
- **level 자체 분류** (설정값):
  - `< 20` → 1 (한산)
  - `20-40` → 2
  - `40-60` → 3 (보통)
  - `60-80` → 4
  - `≥ 80` → 5 (혼잡)
- **매일 새벽 sync**로 30일 예측 갱신
- **30일 예측 + 7일 과거 보관**, 그 이상 cold storage
- **UI 연동**: 스팟 카드 🟢🟡🔴 마이크로 인디케이터, 코스 추천 시 "혼잡 회피" 가중치, COURSE_DECISIONS에 회피 사유 로그

#### TAGS ⭐

- **통제 어휘 + 자유 태그 마스터**
- **카테고리 10종**: mood / view / companion / activity / time / season / price / vibe / theme / facility
- **canonical_tag_id**: 자기 참조 FK, 동의어 자동 머지 (NULL이면 자기 자신이 정규)
- **canonical 정책 (트리거 강제)**:
  1. 정규 태그는 항상 root (`canonical_tag_id IS NULL`)
  2. 동의어는 항상 root만 참조 (다단계 체인 차단)
  3. 사후 변경 차단 (잘못된 매핑 발견 시 `is_active=false` + 새 태그 INSERT)
- **LLM 추출 흐름**:
  - 추출 → TAGS 유사도 검색
  - `≥ 0.92` → 기존 태그로 매핑
  - `0.85 ~ 0.92` → 신규 등록 + 관리자 검토
  - `< 0.85` → 자동 신규 등록 (`tag_type='free'`)
- **검색 시 확장**: 사용자 쿼리 임베딩 → 유사도 ≥ 0.85 후보 → 후보 태그 달린 스팟 검색
- **출시 전 100~150개 controlled 태그 시드 + 임베딩 미리 생성**

#### SPOT_TAGS

- **score 3단계**:
  - `< 0.5` → 저장 안 함 (잡음)
  - `0.5 ~ 0.8` → 약한 신호 (정렬 가중치만)
  - `≥ 0.8` → 강한 신호 (검색·필터 사용)
- **정규 태그 ID만 저장** (검색 단순화)
- **직접 INSERT 금지**: 정규화 함수 거쳐야
- **overview_hash 변경 시**: `source='llm'`만 DELETE-then-INSERT (`manual` 보존)

---

### 🎉 행사 도메인

#### EVENTS_CORE (Hot)

- **event_period generated column**:
  ```sql
  event_period daterange GENERATED ALWAYS AS
    (daterange(event_start_date, event_end_date, '[]')) STORED
  ```
- **venue_spot_id nullable**: NULL = 매칭 없음 또는 일반 장소
- **indoor**: LLM 추정 (비 오는 날 필터)
- **expected_concentration**: festival_grade + LLM 추정, `expected_concentration_source` (rule/llm/manual) 추적
- **종료 행사 자동 비활성화 cron**: 매일 새벽 `event_end_date < TODAY AND is_active=true` → `is_active=false`
- **자동 한끗 생성**: 다가올 7일 행사 → HANKKUT pending (`source='auto_event'`)

#### EVENT_DETAILS / EVENT_EMBEDDINGS / EVENTS_RAW_SNAPSHOTS / EVENT_IMAGES

- **SPOTS와 동일 패턴**

---

### 🚌 공식 코스 도메인

#### TRAVEL_COURSES

- **TourAPI ContentTypeId=25** (한국관광공사 공식 여행코스)
- **부산 ~50건 수준** → row 매우 적음, hot/cold 분리 미적용
- **TourAPI 원본 충실 보존**: `taketime`/`distance` 원문 + `_minutes`/`_km` 파싱본
- **"짠내 버전" 변환 흐름**: TRAVEL_COURSES → COURSE_ITEMS 매칭 스팟 → 가성비 대체 → GENERATED_COURSES 생성

#### COURSE_ITEMS

- **(course_content_id, serial_num) UK**
- **matched_spot_id nullable**: SPOTS_CORE 매칭 실패 시 NULL
- *sub_ fallback 컬럼**: 매칭 실패 시 원본 표시
- **sub_image_alt**: 접근성·SEO

---

### 💰 착한가격 도메인

#### GOOD_PRICE_SHOPS ⭐

- **부산 ~600건 수준**
- **좌표 부재** → 카카오 지오코딩 (`geocoded_at`/`geocoded_source`/`geocode_failed` 추적)
- **영업시간 정규화**: 룰 기반 우선 → 실패 시 BUSINESS_HOURS_REVIEW_QUEUE
- **match_status**:
  - `pending` — 매칭 대기
  - `matched` — SPOTS_CORE 연결 성공
  - `unmatched` — 매칭 실패 (별도 row 생성 X)
  - `separate` — 매칭 실패하여 별도 SPOTS_CORE row 생성 (지도 마커용)
- **matched_spot_id 단방향 SoT** (SPOTS_CORE.good_price_shop_id 제거됨)
- **음식점만 매칭/생성**: `category_code='602'`만 SPOTS_CORE 연결
- **이미용·목욕(603/604)**: GOOD_PRICE_SHOPS만 보관 (코스 추천 미사용)
- **creatDt 파싱**: `YYYYMMDDHHMMSS` 14자리 → timestamp (KST)
- **비활성 처리**: API에서 사라지면 `is_active=false` + `inactive_since=NOW()` (재등장 시 `is_active=true`, `inactive_since=NULL`)

#### GOOD_PRICE_MATCH_QUEUE ⭐

- **가중치**:
  - 전화번호 0.5 (가장 강력)
  - 이름 유사도 0.3 (Jaro-Winkler)
  - 주소 유사도 0.15
  - 거리 0.05 (보조)
- **임계값 3단계**:
  - `≥ 0.85` → 자동 approved + SPOTS_CORE 연결
  - `0.65 ~ 0.85` → pending (관리자 검토)
  - `< 0.65` → 큐 미진입 (separate 처리)
- **1단계 필터** (false negative 줄이기):
  - 같은 시군구 (`l_dong_signgu_cd` 일치)
  - 카테고리 호환 (착한가격 음식점 ↔ TourAPI ContentTypeId=39)
  - 좌표 거리 200m 이내
- **회귀 검증**: 임계값/가중치 변경 시 정답 셋 100쌍

#### GOOD_PRICE_SHOP_PRICES ⭐

- **조회 SoT**: 서비스 화면/코스 계산에서 참조하는 "현재 확정가"
- **대상 제한**: 초기엔 `GOOD_PRICE_SHOPS.match_status='matched' AND matched_spot_id IS NOT NULL` 업소만 운영
- **품목 단위**: `(shop_id, item_name)` 1행 유지 (upsert)
- **갱신 경로**: 오직 승인된 report 반영으로만 update
- **코스 반영**: 코스 생성 시 `expected_cost`/`total_savings` 계산의 1차 기준

#### GOOD_PRICE_PRICE_OBSERVATIONS ⭐

- **append-only 이력**: admin 수기 입력 + user 제보를 동일 스키마로 축적
- **source_type**: `admin_manual` / `user_report` / `crawler`(향후 예약)
- **report_status**:
  - `pending` — 검수 대기
  - `approved` — `GOOD_PRICE_SHOP_PRICES` 반영 완료
  - `rejected` — 반영 제외, 이력 보존
- **증빙 필드**: `evidence_type` + `evidence_ref` (영수증/사진/텍스트)
- **품질 가드레일**:
  - 동일 `(shop_id, item_name, reported_price, observed_at::date)` 중복 제보 병합
  - 1유저 1업소 24시간 제보 횟수 제한(스팸 방지)
  - 승인/반려 사유 필수 기록 (`reviewer_note`)

#### 가격 운영 플로우 (초기 MVP)

1. 운영자가 가격 확인 후 `GOOD_PRICE_PRICE_OBSERVATIONS(source_type='admin_manual', report_status='approved')` INSERT  
2. 트랜잭션 내 `GOOD_PRICE_SHOP_PRICES` UPSERT + `current_price_observation_id` 연결  
3. 사용자 제보는 `pending`으로 적재 후 관리자 검수  
4. 승인 건만 `GOOD_PRICE_SHOP_PRICES` 반영 (반려 건은 이력만 유지)

#### DDD/MSA 확장 대비 참조 정책 (1단계)

- **지금 당장 경계 FK를 일괄 제거하지 않음**: 초기 운영 안정성과 데이터 품질을 우선
- **즉시 적용 범위는 순환 참조 제거**: 가격 도메인은 `GOOD_PRICE_SHOP_PRICES.current_price_observation_id` 단방향만 유지
- **경계 FK는 soft reference로 전환 가능한 형태로만 사용**:
  - 코드에서 FK 직접 조인 의존 최소화
  - API/서비스 레이어에서 ID 기반 조회·검증으로 통일
- **분리 직전(2단계)에서 경계 FK 제거**: User/Spot 경계 참조는 제거 후 이벤트+리컨실리에이션으로 대체

#### CSV 온보딩 (행정안전부 착한가격 파일)

- **현재 CSV 컬럼셋은 ERD와 호환**: `시도, 시군, 업종, 업소명, 연락처, 주소, 메뉴1~3, 가격1~3`는 초기 적재 가능
- **권장 적재 흐름**: `RAW(staging)` → `GOOD_PRICE_SHOPS` 업소 정규화 → `GOOD_PRICE_SHOP_PRICES` 품목 정규화
- **핵심 원칙**: 메뉴/가격은 열 구조(`menu1~3`) 그대로 보관하지 않고, `(shop_id, item_name)` 행 구조로 펼쳐 UPSERT

##### 컬럼 매핑 (CSV → 정규화 테이블)

- `시도 + 시군` → `GOOD_PRICE_SHOPS.l_dong_signgu_cd` 파생(코드 매핑 가능 시), 원문은 staging에 보관
- `업종` → `GOOD_PRICE_SHOPS.category_name` (내부 코드 매핑: 예 `기타요식업/한식/양식 -> 602`, `미용업 -> 603`)
- `업소명` → `GOOD_PRICE_SHOPS.name`
- `연락처` → `GOOD_PRICE_SHOPS.tel` (하이픈/공백 정규화)
- `주소` → `GOOD_PRICE_SHOPS.addr`
- `메뉴N + 가격N` → `GOOD_PRICE_SHOP_PRICES.item_name/current_price` (N=1..3, 빈 값 skip)

##### 중복/품질 규칙

- **업소 키**: 외부 고유 ID 부재 시 `sha1(시도|시군|업소명|주소|연락처)` 기반 임시 `external_id` 생성
- **메뉴 키**: `(shop_id, item_name)` 기준 1행 유지, 동일 키 재유입 시 최신 데이터로 UPSERT
- **가격 파싱**: 숫자 변환 불가 값은 폐기하지 말고 staging 오류 사유 컬럼에 기록
- **결측 처리**: `메뉴` 또는 `가격` 둘 중 하나라도 비어 있으면 해당 품목 row는 미생성
- **추적성**: 적재 배치마다 `source_file`, `loaded_at`, `run_id(sync_logs.id)`를 staging에 남김

---

### 🌤️ 코드/날씨 마스터

#### LDONG_CODES

- **TourAPI 법정동 마스터** (모든 도메인 지역 코드 SoT)
- **부산 16개 시군구 시드 등록**
- **변경 빈도 매우 낮음** (행정구역 개편 시만)
- **전국 확장**: ~250 row

#### LCLS_SYSTM_CODES

- **TourAPI 분류체계** (대/중/소분류 3단)
- **TourAPI 응답 시드 등록** (~수백 row)

#### WEATHER_GRIDS

- **부산 시군구별 기상청 LCC 격자 좌표**
- **부산 16개 시드 등록**
- **시군구 단위 거시 날씨**로 충분 (스팟 단위 정밀 날씨 미적용)

#### WEATHER_CACHE

- **PostgreSQL 유지 이유**: 시계열·범위 쿼리 적합 (Redis 부적합)
- **TTL**: 15분 (`expires_at = fetched_at + 15분`)
- **기상청 표준 코드**:
  - `pty` (강수형태): 0(없음)/1(비)/2(비눈)/3(눈)/5(빗방울)/6(빗방울눈)/7(눈날림)
  - `sky_condition` (하늘상태): 1(맑음)/3(구름많음)/4(흐림)
- **미래 24시간 예보 보관**, 과거 7일 후 cron 삭제
- **코스 생성 시점 날씨**: GENERATED_COURSES.weather_at_gen JSONB로 별도 스냅샷 (이력 추적)

#### GOOD_PRICE_LOCALE_CODES

- **착한가격 API locale 코드 마스터** (GOOD_PRICE_SHOPS.locale_code SoT)
- **LDONG_CODES.signgu_cd에 매핑되는 브리지 테이블**로 사용
- **초기 시드**: 부산 행정동 코드 전체 등록 (운영 중 변경 빈도 낮음)
- **갱신 정책**: 반기 1회 점검 + API 응답 신규 코드 발견 시 수동 승인 추가
- **무결성 규칙**: 미등록 locale_code 유입 시 GOOD_PRICE_SHOPS 적재 실패로 처리하고 SYNC_LOGS에 경고 기록

---

### 🛠️ 운영 도메인

#### SYNC_LOGS ⭐

- **모든 sync/cron/매칭/LLM/회귀 job 통합 추적**
- **job 카테고리**:
  - 데이터 수집: tourapi_spots/events/courses/congestion_sync, goodprice_sync
  - 지오코딩: goodprice_geocoding
  - LLM: spot_overview_summary, spot_tags_extract, spot/event/course_embedding, business_hours_normalize
  - 매칭: goodprice_matching, congestion_matching, course_items_matching
  - 사용자 임베딩: user_embedding_recompute
  - 캐시 갱신: today_concentration_cache_refresh, avg_rating_recalc, bookmark_count_recalc
  - 자동 한끗: hankkut_auto_event_generation, hankkut_archive_expired
  - 정리: weather_cache_cleanup, soft_delete_purge
  - 회귀: embedding_full_recompute, business_hours_regression_test
  - 모니터링: is_open_now_perf_check
- **metadata 표준 필드**:
  ```json
  {
    "model_name": "gpt-4o-mini",
    "model_version": "...",
    "prompt_version": "v2.3",
    "chunk_size": 1000,
    "current_page": 5,
    "total_pages": 12,
    "warnings": ["..."],
    "regression_pass_rate": 0.96,
    "auto_applied": 850,
    "queued_review": 120,
    "rejected": 30,
    "is_open_now_avg_ms": 0.04,
    "is_open_now_p95_ms": 0.12
  }
  ```
- **좀비 job timeout**: 24시간 이상 running → failed 자동 전환 cron
- **보존 정책**:
  - `success`: 1년 후 cron hard delete
  - `failed`: 영구 보관

---

## 4. 대표 쿼리 (인덱스 설계 근거)

### Q1. 지도 뷰포트 스팟 조회 (가장 핫함)

```sql
SELECT content_id, title, map_x, map_y, first_image2,
       price_level, today_concentration_rate, avg_rating, is_good_price
FROM spots_core
WHERE ST_DWithin(geog, ST_MakePoint(:lng, :lat)::geography, :radius_m)
  AND is_active = true
  AND lcls_systm_1 = ANY(:categories)         -- 옵션
  AND is_open_now(content_id) = true          -- 옵션
ORDER BY popularity_score DESC
LIMIT 100;
```

- 인덱스: `gist(geog) WHERE is_active=true`

### Q2. 시군구별 카테고리 스팟 목록

```sql
SELECT content_id, title, ...
FROM spots_core
WHERE l_dong_signgu_cd = :signgu
  AND is_active = true
  AND is_good_price = true                    -- 옵션
  AND price_level <= :max_price_level         -- 옵션
ORDER BY trend_score DESC
LIMIT 50 OFFSET :offset;
```

- 인덱스: `(l_dong_signgu_cd, trend_score DESC) WHERE is_active=true`

### Q3. 자연어 검색 (의미 검색)

```sql
WITH query_embedding AS (SELECT :embedding::vector AS vec)
SELECT s.content_id, s.title, s.first_image,
       1 - (e.embedding <=> q.vec) AS similarity
FROM spot_embeddings e
JOIN spots_core s ON s.content_id = e.content_id
CROSS JOIN query_embedding q
WHERE s.is_active = true
  AND s.l_dong_signgu_cd = :signgu            -- 옵션
ORDER BY e.embedding <=> q.vec
LIMIT 30;
```

- 인덱스: `hnsw(embedding vector_cosine_ops)`

### Q4. 스팟 상세 (FK JOIN)

```sql
SELECT s.*, d.*, ...
FROM spots_core s
LEFT JOIN spot_details d ON d.content_id = s.content_id
LEFT JOIN spot_tags st ON st.content_id = s.content_id AND st.score >= 0.8
LEFT JOIN tags t ON t.tag_id = st.tag_id
LEFT JOIN spot_images i ON i.content_id = s.content_id
WHERE s.content_id = :id;
```

- 주의: 애플리케이션 레벨에서 분리 조회 권장 (N+1 회피)

### Q5. 오늘 행사 (홈 화면)

```sql
SELECT content_id, title, first_image2, l_dong_signgu_cd, festival_grade, ...
FROM events_core
WHERE event_period @> CURRENT_DATE
  AND is_active = true
  AND l_dong_regn_cd = :busan_regn_cd
ORDER BY
  CASE festival_grade WHEN '대표축제' THEN 1 WHEN '최우수' THEN 2 ELSE 3 END,
  event_start_date;
```

- 인덱스: `gist(event_period) WHERE is_active=true`

### Q6. 사용자 북마크 목록

```sql
SELECT b.id, b.created_at, ...
FROM bookmarks b
LEFT JOIN spots_core s ON s.content_id = b.spot_content_id AND s.is_active = true
LEFT JOIN generated_courses gc ON gc.id = b.generated_course_id AND gc.deleted_at IS NULL
LEFT JOIN events_core e ON e.content_id = b.event_content_id AND e.is_active = true
LEFT JOIN hankkut h ON h.id = b.hankkut_id AND h.deleted_at IS NULL
WHERE b.user_id = :user_id
  AND b.collection_id = :collection_id
ORDER BY b.created_at DESC
LIMIT 50;
```

- 인덱스: `(collection_id, created_at DESC)`
- 주의: type별 분리 조회 권장

### Q7. 코스 생성 시 스팟 후보 추출 (가장 무거움)

```sql
SELECT s.content_id, s.title, s.geog, s.lcls_systm_1, s.price_level,
       s.today_concentration_rate, s.is_good_price, s.indoor, d.business_hours
FROM spots_core s
LEFT JOIN spot_details d ON d.content_id = s.content_id
WHERE s.l_dong_signgu_cd = :signgu
  AND s.is_active = true
  AND s.price_level <= :budget_level
  AND (NOT :rainy_day OR s.indoor = true)
  AND is_open_now(s.content_id)
  AND s.today_concentration_rate < 70
ORDER BY s.popularity_score DESC
LIMIT 200;
```

- 인덱스: `(l_dong_signgu_cd, popularity_score DESC) WHERE is_active=true`

### Q8. BHR_QUEUE 검수 대기 (관리자)

```sql
SELECT bhr.*, s.title
FROM business_hours_review_queue bhr
JOIN spots_core s ON s.content_id = bhr.content_id
WHERE bhr.review_status = 'pending'
ORDER BY bhr.confidence ASC, bhr.created_at ASC
LIMIT 50;
```

- 인덱스: `(confidence ASC) WHERE review_status='pending'`

---

## 5. 인덱스 초안 (출시 시점 적용)

### 원칙

- ERD에 적힌 모든 인덱스 만들지 말 것 (안 쓰이는 인덱스가 INSERT 느리게 함)
- 출시 시점엔 **위 Q1~Q8을 지원하는 최소 인덱스만**
- 데이터 적재 후 `EXPLAIN ANALYZE`로 검증하며 점진 확장
- 모든 PK / UK / FK 컬럼 인덱스는 기본 (PostgreSQL은 FK 자동 인덱스 X)

### SPOTS_CORE

```sql
CREATE INDEX idx_spots_geog_active
  ON spots_core USING gist(geog)
  WHERE is_active = true;

CREATE INDEX idx_spots_signgu_pop
  ON spots_core (l_dong_signgu_cd, popularity_score DESC)
  WHERE is_active = true;

CREATE INDEX idx_spots_signgu_trend
  ON spots_core (l_dong_signgu_cd, trend_score DESC)
  WHERE is_active = true;

CREATE INDEX idx_spots_title_trgm
  ON spots_core USING gin(title gin_trgm_ops);
```

### SPOT_EMBEDDINGS

```sql
CREATE INDEX idx_spot_embeddings_hnsw
  ON spot_embeddings USING hnsw(embedding vector_cosine_ops);
```

### EVENTS_CORE

```sql
CREATE INDEX idx_events_period_active
  ON events_core USING gist(event_period)
  WHERE is_active = true;

CREATE INDEX idx_events_geog_active
  ON events_core USING gist(geog)
  WHERE is_active = true;

CREATE INDEX idx_events_signgu_start
  ON events_core (l_dong_signgu_cd, event_start_date)
  WHERE is_active = true;
```

### BOOKMARKS

```sql
CREATE UNIQUE INDEX uk_bookmarks_user_spot
  ON bookmarks(user_id, spot_content_id)
  WHERE spot_content_id IS NOT NULL;
-- (course/event/hankkut 동일 패턴 4개)

CREATE INDEX idx_bookmarks_collection_created
  ON bookmarks(collection_id, created_at DESC);
```

### BUSINESS_HOURS_REVIEW_QUEUE

```sql
CREATE INDEX idx_bhr_pending_confidence
  ON business_hours_review_queue(confidence ASC)
  WHERE review_status = 'pending';

CREATE UNIQUE INDEX uk_bhr_pending_content
  ON business_hours_review_queue(content_id)
  WHERE review_status = 'pending';
```

### USER_REVIEWS

```sql
CREATE UNIQUE INDEX uk_user_reviews_user_spot_active
  ON user_reviews(user_id, spot_content_id)
  WHERE deleted_at IS NULL;

CREATE INDEX idx_user_reviews_spot_created
  ON user_reviews(spot_content_id, created_at DESC)
  WHERE deleted_at IS NULL;
```

### GENERATED_COURSES

```sql
CREATE UNIQUE INDEX uk_gen_courses_share_token
  ON generated_courses(share_token);

CREATE INDEX idx_gen_courses_user_created
  ON generated_courses(user_id, created_at DESC)
  WHERE deleted_at IS NULL;
```

### 점진 확장 모니터링 쿼리

```sql
-- 느린 쿼리 추적
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;

-- 안 쓰이는 인덱스
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY pg_relation_size(indexrelid) DESC;
```

---

## 6. 데이터 흐름 책임 매트릭스

> 파이썬 파이프라인과 Spring 백엔드가 같은 DB를 쓰므로 권한·책임 분리가 필수.


| 테이블                               | 파이썬 (R/W)            | Spring (R/W) | 비고                     |
| --------------------------------- | -------------------- | ------------ | ---------------------- |
| SPOTS_CORE                        | RW                   | R            | 마스터, 파이썬 SoT           |
| SPOT_DETAILS                      | RW                   | R            |                        |
| SPOT_EMBEDDINGS                   | RW                   | R            |                        |
| SPOTS_RAW_SNAPSHOTS               | RW                   | -            | 파이썬 단독                 |
| SPOT_IMAGES                       | RW                   | R            |                        |
| SPOT_TAGS                         | RW                   | R            |                        |
| SPOT_CONGESTION_FORECAST          | RW                   | R            |                        |
| EVENTS_CORE                       | RW                   | R            |                        |
| EVENT_DETAILS                     | RW                   | R            |                        |
| EVENT_EMBEDDINGS                  | RW                   | R            |                        |
| EVENTS_RAW_SNAPSHOTS              | RW                   | -            |                        |
| EVENT_IMAGES                      | RW                   | R            |                        |
| TRAVEL_COURSES                    | RW                   | R            |                        |
| TRAVEL_COURSE_EMBEDDINGS          | RW                   | R            |                        |
| COURSES_RAW_SNAPSHOTS             | RW                   | -            |                        |
| COURSE_ITEMS                      | RW                   | R            |                        |
| GOOD_PRICE_SHOPS                  | RW                   | R            |                        |
| GOOD_PRICE_SHOP_PRICES            | R                    | RW           | 확정 가격 SoT는 Spring      |
| GOOD_PRICE_PRICE_OBSERVATIONS     | R                    | RW           | 1단계: Spring 입력/검수 SoT, 파이썬은 조회만 |
| GOOD_PRICE_MATCH_QUEUE            | RW                   | RW           | 양쪽: 파이썬 큐잉, Spring 검수  |
| GPS_RAW_SNAPSHOTS                 | RW                   | -            |                        |
| TAGS                              | RW                   | R            | 파이썬 자동 추가, Spring 검색만  |
| WEATHER_CACHE                     | RW                   | R            | 파이썬 sync, Spring 조회    |
| WEATHER_GRIDS                     | R (시드)               | R            | 마스터                    |
| LDONG_CODES                       | R (시드)               | R            | 마스터                    |
| LCLS_SYSTM_CODES                  | R (시드)               | R            | 마스터                    |
| GOOD_PRICE_LOCALE_CODES           | R (시드)               | R            | 마스터                    |
| **USERS**                         | -                    | RW           | Spring 단독              |
| **USER_EMBEDDINGS**               | RW (배치)              | R            | 양쪽: 파이썬 재계산, Spring 조회 |
| **BOOKMARKS**                     | -                    | RW           | Spring 단독              |
| **BOOKMARK_COLLECTIONS**          | -                    | RW           | Spring 단독              |
| **GENERATED_COURSES**             | -                    | RW           | Spring 단독              |
| **GENERATED_COURSE_ITEMS**        | -                    | RW           | Spring 단독              |
| **COURSE_DECISIONS**              | -                    | RW           | Spring 단독              |
| **USER_REVIEWS**                  | -                    | RW           | Spring 단독              |
| **VISIT_HISTORY**                 | -                    | RW           | Spring 단독              |
| **NOTIFICATIONS**                 | -                    | RW           | Spring 단독              |
| **HANKKUT**                       | RW (auto_event cron) | RW (관리자)     | 양쪽                     |
| **HANKKUT_SPOTS / TAGS / EVENTS** | RW                   | RW           | 양쪽                     |
| BUSINESS_HOURS_REVIEW_QUEUE       | W (LLM 큐잉)           | RW (관리자 검수)  | 양쪽                     |
| SYNC_LOGS                         | RW (자기 job)          | RW (자기 job)  | 양쪽                     |


### DB 권한 분리 SQL

- 이 섹션은 책임 매트릭스만 다루며, 실행 가능한 SQL은 **§12 완성본만 단일 SoT**로 사용
- 중복/불일치 방지를 위해 §6의 예시 SQL은 제거

### 마이그레이션 책임자

- **DDL 변경**: Alembic (파이썬 측 관리) 또는 Flyway (Spring 측 관리) **둘 중 하나만**
- 절대 금지: Hibernate `ddl-auto=update` + SQLAlchemy `create_all` 동시 사용 (충돌 100%)
- **권장**: Alembic 단독 운영 (파이썬 파이프라인이 마스터 데이터를 정의하므로)

---

## 7. 시간대 처리 정책 (반드시 준수)

### 저장

- DB 서버 시간대: **UTC** (변경 금지)
- TIMESTAMPTZ: 자동 UTC 저장
- `business_hours` JSONB: 시간 문자열은 모두 **KST 기준** ("09:00")
- DATE 컬럼 (`base_ymd` 등): **KST 날짜 기준**

### 비교·계산

```sql
-- 영업시간 비교
SELECT * FROM spot_details
WHERE business_hours @> '{...}'::jsonb;
-- 함수 내부에서 (NOW() AT TIME ZONE 'Asia/Seoul') 사용

-- DATE 비교 (KST 오늘)
WHERE base_ymd = (NOW() AT TIME ZONE 'Asia/Seoul')::DATE
```

### 표시

- 사용자 화면: 앱 레이어에서 KST 변환 (Spring `ZonedDateTime`)
- API 응답: ISO 8601 with timezone (`2026-04-26T13:00:00+09:00`)

### 검증 케이스

- KST 23:30 (UTC 14:30) → 영업시간 22:00까지 → false 검증
- KST 00:30 (UTC 15:30, 전날) → 새벽 영업 케이스 정확 판단

---

## 8. is_open_now() 함수 사용 정책

### 함수 시그니처 (DDL 기준)

```sql
-- 실제 구현은 TIMESTAMPTZ 기반, KST 기준으로 판정
CREATE OR REPLACE FUNCTION is_open_now(p_content_id VARCHAR)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE;
```

### 구현 의사코드 (공통 로직 계약)

```text
1) spot_details.business_hours JSONB 조회
2) now_kst = (NOW() AT TIME ZONE 'Asia/Seoul')
3) 요일별 영업구간(weekly) 확인
4) break/holiday/notes 예외 규칙 적용
5) 자정을 넘는 영업구간(예: 18:00~02:00) 별도 분기 처리
6) 영업중이면 true, 아니면 false 반환
```

### 절대 금지

```sql
-- ❌ 단독 사용 (전체 풀스캔, 인덱스 활용 불가)
SELECT * FROM spots_core WHERE is_open_now(content_id);
```

### 올바른 사용

```sql
-- ✅ 인덱스 선행 필터와 결합
SELECT * FROM spots_core
WHERE l_dong_signgu_cd = :signgu      -- 인덱스 활용
  AND is_active = true                  -- 인덱스 활용
  AND is_open_now(content_id);          -- 좁혀진 후 함수 호출

-- ✅ 공간 검색과 결합
SELECT * FROM spots_core
WHERE ST_DWithin(geog, :center, 2000)   -- GiST 인덱스
  AND is_active = true
  AND is_open_now(content_id);
```

### 모니터링

- SYNC_LOGS metadata에 `is_open_now_avg_ms`, `is_open_now_p95_ms`, `is_open_now_call_count` 기록
- 전국 확장 트리거 (캐시 도입 검토): 활성 5만 row 또는 평균 100ms 초과 또는 p95 > 500ms 1주 지속

---

## 9. TAGS canonical_tag_id 운영 정책 (트리거 강제)

### 절대 금지

- 기존 태그의 `canonical_tag_id` 사후 변경 (NULL 변경 포함)
- canonical이 또 다른 canonical을 가리키는 다단계 체인
- SPOT_TAGS 직접 INSERT (정규화 함수 거쳐야)

### 권장 흐름 (잘못된 매핑 발견 시)

1. 해당 태그 `is_active = false` 비활성화
2. 새 태그 INSERT (올바른 canonical_tag_id)
3. 영향받은 SPOT_TAGS는 다음 임베딩 재추출 시 자동 정정

---

## 10. 인증·권한 정책 (확정)

### 비로그인 가능 (콘텐츠 열람만)

- 스팟 / 공식 코스 / 공유 코스 / 한끗 / 행사 열람

### 로그인 필수 (쓰기 + 개인화)

- 코스 생성·저장·공유, 북마크·컬렉션, 리뷰·방문 기록, 알림 수신

### 인증 방식

- 카카오 / 네이버 / 구글 OAuth
- 익명 사용자 미운영

### Rate Limiting

- 코스 생성: 1유저 시간당 5회
- 리뷰 작성: 1유저 시간당 5회
- view_count: 1유저 1코스 1시간 1회 (비로그인 열람은 증가 X)

---

## 11. 컬럼 타입 강제 규칙 (DDL 작성 시 필수)

### 11.1 시각 컬럼은 무조건 TIMESTAMPTZ

**ERD 머메이드 표기는 `timestamp`이지만, 실제 DDL은 모두 `TIMESTAMPTZ`로 작성한다.**


| ERD 표기      | 실제 DDL        | 이유                           |
| ----------- | ------------- | ---------------------------- |
| `timestamp` | `TIMESTAMPTZ` | UTC 자동 변환 저장, timezone 정보 보존 |
| `date`      | `DATE`        | KST 기준 날짜                    |
| `time`      | `TIME`        | KST 기준 시각 (예: arrival_time)  |


### 11.2 적용 대상 (예외 없음)

모든 테이블의 다음 컬럼들은 `TIMESTAMPTZ`:

- `created_at`, `updated_at`, `deleted_at`
- `synced_at`, `fetched_at`, `embedded_at`
- `last_active_at`, `published_at`, `read_at`, `reviewed_at`
- `started_at`, `ended_at`
- `inactive_since`, `concentration_updated_at`, `rating_updated_at`, `trend_updated_at`
- `business_hours_parsed_at`, `business_hours_verified_at`, `business_hours_stale_after`
- `geocoded_at`, `source_modified_time`, `source_created_at`, `created_time`
- `expires_at`, `observed_at` (WEATHER_CACHE)

### 11.3 DEFAULT 값

```sql
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
-- updated_at 자동 갱신은 트리거 또는 애플리케이션 레벨
```

### 11.4 검증 SQL

DDL 적용 후 다음 쿼리로 위반 컬럼 없는지 검증:

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND data_type = 'timestamp without time zone'  -- 위반 케이스
ORDER BY table_name;
-- 결과 = 0 row 이어야 함
```

---

## 12. DB 권한 분리 SQL (완성본 - SEQUENCE 포함)

> 출시 전 반드시 적용. SEQUENCE 권한 누락 시 `BIGSERIAL` INSERT 실패.

### 12.1 파이썬 파이프라인 사용자

```sql
CREATE USER pipeline_user WITH PASSWORD :'pipeline_pw';
 
-- 데이터베이스 연결 권한
GRANT CONNECT ON DATABASE nolleo TO pipeline_user;
GRANT USAGE ON SCHEMA public TO pipeline_user;
 
-- 마스터 데이터 RW (파이썬이 SoT)
GRANT INSERT, UPDATE, DELETE, SELECT ON
  spots_core, spot_details, spot_embeddings, spots_raw_snapshots,
  spot_images, spot_tags, spot_congestion_forecast,
  events_core, event_details, event_embeddings, events_raw_snapshots, event_images,
  travel_courses, travel_course_embeddings, courses_raw_snapshots, course_items,
  good_price_shops, gps_raw_snapshots,
  tags, weather_cache,
  user_embeddings,
  sync_logs
TO pipeline_user;
 
-- 양쪽 RW (상태 전이 규칙은 §13 참조)
GRANT INSERT, UPDATE, SELECT ON
  good_price_match_queue,
  business_hours_review_queue,
  hankkut, hankkut_spots, hankkut_tags, hankkut_events
TO pipeline_user;
 
-- 마스터 코드 (읽기만)
GRANT SELECT ON
  good_price_price_observations,  -- 1단계: 파이썬은 조회만, 2단계(crawler)부터 INSERT 부여
  good_price_shop_prices,
  weather_grids, ldong_codes, lcls_systm_codes, good_price_locale_codes
TO pipeline_user;
 
-- 사용자 데이터 (분석용 읽기, 쓰기 금지)
GRANT SELECT ON
  users, bookmarks, bookmark_collections,
  generated_courses, generated_course_items, course_decisions,
  user_reviews, visit_history, notifications
TO pipeline_user;
 
-- ⭐ SEQUENCE 권한 (BIGSERIAL INSERT 위해 필수)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pipeline_user;
 
-- ⭐ 앞으로 만들 시퀀스에도 자동 적용
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO pipeline_user;
 
-- ⭐ 앞으로 만들 테이블 권한 자동 적용 (선택)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO pipeline_user;
```

### 12.2 Spring 백엔드 사용자

```sql
CREATE USER app_user WITH PASSWORD :'app_pw';
 
GRANT CONNECT ON DATABASE nolleo TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
 
-- 마스터 데이터 (Spring은 읽기만)
GRANT SELECT ON
  spots_core, spot_details, spot_embeddings, spot_images, spot_tags,
  spot_congestion_forecast,
  events_core, event_details, event_embeddings, event_images,
  travel_courses, travel_course_embeddings, course_items,
  good_price_shops,
  tags, weather_cache, weather_grids,
  ldong_codes, lcls_systm_codes, good_price_locale_codes,
  user_embeddings  -- 파이썬이 갱신, Spring은 조회만
TO app_user;
 
-- 사용자 데이터 RW (Spring SoT)
GRANT INSERT, UPDATE, DELETE, SELECT ON
  users, bookmarks, bookmark_collections,
  generated_courses, generated_course_items, course_decisions,
  user_reviews, visit_history, notifications,
  good_price_shop_prices
TO app_user;
 
-- 양쪽 RW (상태 전이 규칙은 §13 참조)
GRANT INSERT, UPDATE, SELECT ON
  good_price_price_observations,
  good_price_match_queue,
  business_hours_review_queue,
  hankkut, hankkut_spots, hankkut_tags, hankkut_events,
  sync_logs
TO app_user;
 
-- ⭐ SEQUENCE 권한
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
 
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_user;
 
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO app_user;
```

### 12.3 권한 검증

```sql
-- 적용 후 권한 확인
\du pipeline_user
\du app_user
 
-- 특정 테이블 권한 확인
SELECT grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_name = 'spots_core';
 
-- 시퀀스 권한 확인
SELECT grantee, privilege_type
FROM information_schema.role_usage_grants
WHERE object_type = 'SEQUENCE';
```

---

## 13. 양쪽 RW 테이블의 상태 전이 소유권

> 같은 테이블을 파이썬과 Spring이 모두 쓸 때 race condition / 의도 모순 방지를 위한 상태 전이 책임 분리.

### 13.1 GOOD_PRICE_MATCH_QUEUE


| 작업                          | 파이썬        | Spring       |
| --------------------------- | ---------- | ------------ |
| INSERT (status='pending')   | ✅ 매칭 후보 등록 | ❌ 금지         |
| UPDATE (pending → approved) | ❌ 금지       | ✅ 관리자 검수     |
| UPDATE (pending → rejected) | ❌ 금지       | ✅ 관리자 검수     |
| UPDATE (이미 처리된 row)         | ❌ 절대 금지    | ❌ 절대 금지 (감사) |
| DELETE                      | ❌ 금지       | ❌ 금지 (이력 보존) |


**자동 처리 (score ≥ 0.85)**: 파이썬이 직접 GOOD_PRICE_SHOPS.matched_spot_id 갱신, MATCH_QUEUE 미경유.

### 13.2 BUSINESS_HOURS_REVIEW_QUEUE


| 작업                          | 파이썬             | Spring   |
| --------------------------- | --------------- | -------- |
| INSERT (status='pending')   | ✅ LLM 정규화 결과 큐잉 | ❌ 금지     |
| UPDATE (pending → approved) | ❌ 금지            | ✅ 관리자 검수 |
| UPDATE (pending → rejected) | ❌ 금지            | ✅ 관리자 검수 |
| approved 후 SPOT_DETAILS 갱신  | ❌ Spring이 처리    | ✅        |


**자동 적용 (confidence ≥ 0.85 + validation_passed)**: 파이썬이 직접 SPOT_DETAILS.business_hours 갱신, BHR_QUEUE 미경유. → SPOT_DETAILS는 파이썬 SoT이므로 OK.

### 13.3 HANKKUT


| 작업                                             | 파이썬 (auto_event cron)                    | Spring (관리자) |
| ---------------------------------------------- | ---------------------------------------- | ------------ |
| INSERT (status='pending', source='auto_event') | ✅ 다가올 7일 행사 자동 큐잉                        | ❌            |
| INSERT (source='manual')                       | ❌                                        | ✅ 관리자 작성     |
| UPDATE (pending → approved/rejected)           | ❌ 절대 금지                                  | ✅ 관리자 검수     |
| UPDATE (approved → archived)                   | ✅ 단, 시즌 종료 cron만 (`valid_until < TODAY`) | ✅ 관리자 수동     |
| UPDATE (approved row 내용 수정)                    | ❌ 절대 금지                                  | ✅ 관리자만       |
| soft delete                                    | ❌ 금지                                     | ✅            |


**규칙 요약**:

- 파이썬이 만진 row는 `status='pending'` 상태에서만
- 한번 `approved`되면 파이썬은 archive 외 수정 금지
- `source='manual'` row는 파이썬이 절대 수정 금지

### 13.4 HANKKUT_SPOTS / HANKKUT_TAGS / HANKKUT_EVENTS


| 작업                                  | 파이썬                | Spring |
| ----------------------------------- | ------------------ | ------ |
| INSERT (자동 생성 한끗의 join)             | ✅ auto_event cron만 | ❌      |
| INSERT (수동 한끗의 join)                | ❌                  | ✅      |
| 직접 INSERT                           | ❌ 금지               | ❌ 금지   |
| **반드시 attachHankkutEvents() 함수 경유** | ✅                  | ✅      |


`attachHankkutEvents()`는 파이썬·Spring 양쪽에 동일한 인터페이스로 구현 (SQL 함수 또는 각 언어의 서비스 레이어 함수).

### 13.5 USER_EMBEDDINGS


| 작업              | 파이썬    | Spring |
| --------------- | ------ | ------ |
| UPSERT (재계산 배치) | ✅ 일 1회 | ❌      |
| SELECT (취향 매칭)  | ❌      | ✅      |
| 모델 변경 시 일괄 재계산  | ✅      | ❌      |


**Spring이 UPDATE 절대 금지** (배치 결과 덮어쓰기 사고 방지).

### 13.6 GOOD_PRICE_PRICE_OBSERVATIONS

| 작업                                                | 파이썬                     | Spring          |
| ------------------------------------------------- | ----------------------- | --------------- |
| INSERT (`source_type='admin_manual'`)             | ❌ 금지                    | ✅ 운영자 수기 입력     |
| INSERT (`source_type='user_report'`)              | ❌ 금지                    | ✅ 사용자 제보 접수     |
| INSERT (`source_type='crawler'`)                  | ⚠️ 2단계부터 허용 (1단계 권한 미부여) | ❌ 금지            |
| UPDATE (`pending → approved/rejected`)            | ❌ 절대 금지                 | ✅ 관리자 검수        |
| approved 후 GOOD_PRICE_SHOP_PRICES 반영             | ❌ 절대 금지                 | ✅ 단일 트랜잭션으로 처리  |
| UPDATE (이미 처리된 row 재수정)                           | ❌ 절대 금지                 | ❌ 절대 금지 (감사 목적) |
| DELETE                                             | ❌ 금지                    | ❌ 금지 (이력 보존)    |

**규칙 요약**:

- 가격 현재값 SoT는 `GOOD_PRICE_SHOP_PRICES`, 변경 근거 SoT는 `GOOD_PRICE_PRICE_OBSERVATIONS`
- `report_status='approved'`가 아니면 `GOOD_PRICE_SHOP_PRICES` 반영 금지
- 수기 입력/유저 제보/향후 크롤러를 `source_type`으로 단일 파이프라인 관리
- `GOOD_PRICE_PRICE_OBSERVATIONS → GOOD_PRICE_SHOP_PRICES` 역참조 FK는 두지 않음 (순환 참조 방지)

### 13.7 SYNC_LOGS


| 작업                    | 파이썬            | Spring            |
| --------------------- | -------------- | ----------------- |
| INSERT (자기 job)       | ✅ 파이썬 job_name | ✅ Spring job_name |
| UPDATE (자기 job 종료 시)  | ✅ 자기 job만      | ✅ 자기 job만         |
| **다른 시스템 job row 수정** | ❌ 절대 금지        | ❌ 절대 금지           |
| DELETE (보존 정책 cron)   | ✅ success 1년 후 | - (파이썬 cron이 담당)  |


**job_name 네임스페이스 규약**:

- 파이썬: `tourapi_*`, `embedding_*`, `llm_*`, `geocoding_*`, `hankkut_auto_*`, `weather_*`, `congestion_*`
- Spring: `user_*`, `course_*`, `notification_*`, `bookmark_*`
- 서로의 prefix 사용 금지

### 13.8 위반 감지 (선택, 강력 권장)

PostgreSQL 트리거로 강제할 수도 있음:

```sql
-- HANKKUT의 source='manual' row를 pipeline_user가 수정 시도하면 차단
CREATE OR REPLACE FUNCTION block_pipeline_manual_hankkut()
RETURNS TRIGGER AS $$
BEGIN
    IF current_user = 'pipeline_user' AND OLD.source = 'manual' THEN
        RAISE EXCEPTION 'pipeline_user cannot modify manual hankkut rows';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
 
CREATE TRIGGER trg_block_pipeline_manual_hankkut
BEFORE UPDATE OR DELETE ON hankkut
FOR EACH ROW EXECUTE FUNCTION block_pipeline_manual_hankkut();

-- 1단계: pipeline_user의 가격 관측 INSERT 차단 (2단계 crawler 도입 시 해제/완화)
CREATE OR REPLACE FUNCTION block_pipeline_observation_insert()
RETURNS TRIGGER AS $$
BEGIN
    IF current_user = 'pipeline_user' THEN
        RAISE EXCEPTION 'pipeline_user cannot insert good_price_price_observations in phase1';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_block_pipeline_observation_insert
BEFORE INSERT ON good_price_price_observations
FOR EACH ROW EXECUTE FUNCTION block_pipeline_observation_insert();
```

MVP는 코드 리뷰 + 운영문서로 충분. MAU 도달 후 트리거 도입 검토.

---

## 14. REPLACE 패턴의 트랜잭션 경계 (강제)

### 14.1 위험 시나리오

```python
# ❌ 잘못됨 (autocommit 또는 분리 트랜잭션)
await conn.execute("DELETE FROM spot_images WHERE content_id=$1", content_id)
# 이 사이에 Spring이 SELECT하면 → 빈 결과 → "이미지 없음" 깜빡임
await conn.executemany("INSERT INTO spot_images ...", rows)
```

### 14.2 강제 규칙

**모든 REPLACE 패턴 작업은 단일 트랜잭션 내에서 DELETE + INSERT 완료**.

대상 테이블 (operations.md §2 REPLACE 분류):

- `SPOT_IMAGES`, `EVENT_IMAGES`
- `COURSE_ITEMS`
- `SPOT_TAGS` (source='llm'만)
- `HANKKUT_SPOTS`, `HANKKUT_TAGS`, `HANKKUT_EVENTS`

### 14.3 올바른 패턴

```python
# ✅ Python (psycopg)
async with conn.transaction():
    await conn.execute(
        "DELETE FROM spot_images WHERE content_id = %s",
        (content_id,)
    )
    await conn.executemany(
        "INSERT INTO spot_images (content_id, origin_img_url, ...) VALUES (%s, %s, ...)",
        rows
    )
# COMMIT 시점에만 외부에 반영 → 깜빡임 없음
```

```java
// ✅ Spring (@Transactional)
@Transactional
public void replaceSpotImages(String contentId, List<SpotImage> images) {
    spotImageRepository.deleteByContentId(contentId);
    spotImageRepository.saveAll(images);
}
```

### 14.4 규모가 클 때 — 스테이징 → 스왑 (선택)

부산 규모(스팟당 5장)는 단일 트랜잭션이면 충분. 전국 확장 + 스팟당 50장 같은 케이스에서만 검토:

```sql
-- 스테이징 테이블에 INSERT
INSERT INTO spot_images_staging SELECT * FROM new_data;
 
-- ATOMIC SWAP
BEGIN;
DELETE FROM spot_images WHERE content_id = :id;
INSERT INTO spot_images SELECT * FROM spot_images_staging WHERE content_id = :id;
DELETE FROM spot_images_staging WHERE content_id = :id;
COMMIT;
```

### 14.5 코드 리뷰 체크리스트

- DELETE + INSERT가 같은 트랜잭션 블록 안에 있는가?
- autocommit 모드 아닌가? (`SET autocommit=0` 또는 명시적 `BEGIN`)
- 예외 발생 시 ROLLBACK 보장되는가? (try/except 또는 with 컨텍스트)
- 트랜잭션 격리수준이 READ COMMITTED 이상인가? (PostgreSQL 기본 OK)

---

## 15. is_open_now() 호출 강제 정책 (4단계 방어)

기존 §8을 확장. 정책만으로는 부족, **코드/CI 레벨 강제 메커니즘** 필수.

### 15.1 1단계: 리포지토리 단일 진입점

**Java/Spring**:

```java
public interface SpotRepository {
    // ✅ 항상 선행 필터와 함께
    List<Spot> findOpenNowBySigngu(String signgu, OpenSearchOptions opts);
    List<Spot> findOpenNowWithinRadius(double lat, double lng, int meters, OpenSearchOptions opts);
    List<Spot> findOpenNowByContentIds(List<String> contentIds);  // 미리 좁혀진 ID 리스트
    
    // ❌ findAllOpenNow() 같은 메서드 절대 만들지 않음
}
```

**Python**:

```python
class SpotRepository:
    async def find_open_now_by_signgu(self, signgu: str, ...) -> list[Spot]: ...
    async def find_open_now_within_radius(self, lat, lng, meters, ...) -> list[Spot]: ...
    
    # ❌ find_all_open_now() 만들지 말 것
```

### 15.2 2단계: ORM/Query Builder 차단

- `is_open_now()`를 ORM의 함수로 노출하지 않음
- Spring JPA `@Query` 또는 QueryDSL 사용 시 함수 호출 헬퍼만 제공
- 항상 헬퍼가 선행 필터(`l_dong_signgu_cd`, `ST_DWithin`, `is_active`) 검증

### 15.3 3단계: DB 함수 자체 안전장치

```sql
ALTER FUNCTION is_open_now(VARCHAR) COST 1000;
-- COST 높이면 옵티마이저가 다른 필터를 먼저 적용하려 함
-- 풀스캔 자체를 막진 않지만 자동 최적화 유도
```

### 15.4 4단계: CI grep 검사 (가장 효과적)

`.github/workflows/check-is-open-now.yml`:

```yaml
name: Check is_open_now() safe usage
 
on: [pull_request, push]
 
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Detect unsafe is_open_now() usage
        run: |
          # 검색 패턴: is_open_now가 등장하는 SQL/Python/Java 파일
          # 같은 쿼리/메서드 블록에 선행 필터가 있는지 검사
          
          UNSAFE_FOUND=0
          
          # SQL 파일 검사
          for file in $(grep -rlE "is_open_now\(" --include="*.sql" --include="*.py" --include="*.java" --include="*.kt"); do
            # is_open_now가 등장하는 줄 주변 ±5줄에 선행 필터 키워드가 있는지
            if ! grep -B5 -A5 "is_open_now(" "$file" | grep -qE "l_dong_signgu_cd|ST_DWithin|content_id\s*=|content_id\s+IN|is_active"; then
              echo "❌ 의심 파일: $file"
              echo "   is_open_now() 호출에 선행 필터(l_dong_signgu_cd/ST_DWithin/content_id=/is_active)가 안 보임"
              UNSAFE_FOUND=1
            fi
          done
          
          if [ $UNSAFE_FOUND -eq 1 ]; then
            echo ""
            echo "운영문서 §8, §15 참조: is_open_now()는 항상 인덱스 선행 필터와 결합해야 합니다."
            exit 1
          fi
          
          echo "✅ is_open_now() 사용 검사 통과"
```

PR 머지 전 자동 실행. 위반 시 머지 차단.

### 15.5 모니터링 (운영 중)

SYNC_LOGS metadata에 함수 호출 통계 기록 (기존 §8과 동일):

```json
{
  "is_open_now_avg_ms": 0.04,
  "is_open_now_p95_ms": 0.12,
  "is_open_now_call_count": 12500
}
```

전국 확장 트리거 (캐시 도입 검토): 활성 5만 row 또는 평균 100ms 초과 또는 p95 > 500ms 1주 지속.

---

## 16. 마이그레이션 도구 단일화 CI 강제

> 기존 §6 (데이터 흐름 매트릭스) 마이그레이션 책임자 항목 보강.

### 16.1 채택 결정

**Alembic 단독 운영** (파이썬 파이프라인이 마스터 데이터 SoT이므로).

Spring 측:

- `application.yml`: `spring.jpa.hibernate.ddl-auto: validate` 강제
- `validate`: 스키마와 엔티티 매핑 검증만, DDL 변경 X
- `none`도 허용. `update`/`create`/`create-drop` 절대 금지.

### 16.2 CI 강제 (.github/workflows/migration-check.yml)

```yaml
name: Migration Tool Single Source Check
 
on: [pull_request, push]
 
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Detect migration tools
        run: |
          # Alembic 흔적
          ALEMBIC_FOUND=0
          if [ -f "alembic.ini" ] || [ -d "alembic/versions" ]; then
            ALEMBIC_FOUND=1
            echo "Alembic detected"
          fi
          
          # Flyway 흔적
          FLYWAY_FOUND=0
          if [ -f "flyway.conf" ] || find . -path ./node_modules -prune -o -path "*/db/migration/V*" -print 2>/dev/null | grep -q .; then
            FLYWAY_FOUND=1
            echo "Flyway detected"
          fi
          
          # 동시 사용 차단
          if [ "$ALEMBIC_FOUND" -eq 1 ] && [ "$FLYWAY_FOUND" -eq 1 ]; then
            echo "❌ Alembic과 Flyway가 동시 발견됨. 하나만 사용해야 합니다."
            echo "운영문서 §16 참조: 본 프로젝트는 Alembic 단독 운영"
            exit 1
          fi
          
      - name: Check Hibernate ddl-auto
        run: |
          if grep -rE "ddl-auto:\s*(update|create|create-drop)" \
              --include="*.yml" --include="*.yaml" --include="*.properties" .; then
            echo "❌ Hibernate ddl-auto가 update/create/create-drop으로 설정됨"
            echo "운영문서 §16: validate 또는 none만 허용"
            exit 1
          fi
          echo "✅ Hibernate ddl-auto 안전 확인"
          
      - name: Check SQLAlchemy create_all
        run: |
          if grep -rE "Base\.metadata\.create_all|create_all\s*\(" \
              --include="*.py" .; then
            echo "❌ SQLAlchemy create_all() 발견"
            echo "운영문서 §16: Alembic 외 DDL 생성 금지"
            exit 1
          fi
          echo "✅ SQLAlchemy create_all() 미사용 확인"
          
      - name: Check raw CREATE TABLE in code
        run: |
          # Alembic versions 디렉토리 외에서 CREATE TABLE 사용 차단
          UNSAFE=$(grep -rE "CREATE TABLE" --include="*.py" --include="*.java" --include="*.kt" \
                   --exclude-dir="alembic" --exclude-dir="tests" --exclude-dir="node_modules" .)
          if [ -n "$UNSAFE" ]; then
            echo "⚠️ 마이그레이션 외부에서 CREATE TABLE 발견:"
            echo "$UNSAFE"
            echo "마이그레이션은 alembic/versions/ 디렉토리에서만 관리하세요"
            # 경고만, 실패 처리는 안 함 (테스트 픽스처 등 예외)
          fi
```

### 16.3 PR 템플릿에 체크리스트 추가

`.github/pull_request_template.md`:

```markdown
## DB 변경 체크리스트 (해당 시)
- [ ] DDL 변경은 alembic/versions/ 에 마이그레이션 파일로 추가했습니까?
- [ ] Hibernate ddl-auto는 validate/none 으로 유지됩니까?
- [ ] SQLAlchemy create_all() 사용하지 않았습니까?
- [ ] is_open_now() 사용 시 선행 필터(시군구/공간/active) 함께 적용했습니까?
- [ ] REPLACE 패턴 작업은 단일 트랜잭션 내에서 처리됩니까?
- [ ] 양쪽 RW 테이블 수정 시 §13의 상태 전이 규칙을 따랐습니까?
```

---

## 17. 출시 전 체크리스트 (이 7개 + 기존 정책 통합)

### 컬럼 타입

- 모든 시각 컬럼이 `TIMESTAMPTZ`인가? (§11.4 검증 SQL 통과)
- DATE/TIME 컬럼은 KST 기준으로 사용되는가?

### 권한

- `pipeline_user`, `app_user` 모두 SEQUENCE 권한 부여됐는가?
- `ALTER DEFAULT PRIVILEGES` 적용으로 미래 시퀀스도 자동 권한 부여되는가?
- BIGSERIAL INSERT 테스트 통과했는가?

### 상태 전이

- §13의 7개 양쪽 RW 테이블 모두 책임자 명확한가?
- job_name 네임스페이스 규약(파이썬 prefix vs Spring prefix) 코드에 반영됐는가?

### 트랜잭션

- 모든 REPLACE 패턴 작업이 단일 트랜잭션인가?
- autocommit 모드 사용 안 하는가?

### is_open_now()

- 리포지토리 레이어에 단일 진입점 메서드만 있는가? (`findAllOpenNow()` 같은 거 없음)
- CI grep 검사 통과하는가?
- 함수 COST 1000 적용됐는가?

### 마이그레이션

- Alembic 단독 운영으로 결정 명문화됐는가?
- Hibernate `ddl-auto: validate` 설정됐는가?
- CI 마이그레이션 도구 검사 통과하는가?
- PR 템플릿 체크리스트 적용됐는가?


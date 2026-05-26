# TourAPI 여행코스( `ContentTypeId=25` ) 적재 가이드

`docs/operation.md`, `docs/erd.md` 기준으로 공식 여행코스 도메인 적재 순서와 운영 체크리스트를 정리한 문서입니다.

---

## 1) 범위와 목표

- 대상 API: TourAPI `ContentTypeId=25` (공식 여행코스)
- 적재 대상 테이블:
  - RAW: `courses_raw_snapshots`
  - 정규화: `travel_courses`
  - 하위 항목: `course_items`
  - (선택) 파생: `travel_course_embeddings`
- 운영 원칙:
  - `travel_courses`: UPSERT
  - `course_items`: **코스 단위 REPLACE(DELETE → INSERT)**, 반드시 단일 트랜잭션

---

## 2) 적재 권장 순서 (실행 순서)

### Step A. 사전 준비

1. `.env` 점검
   - `TOUR_API_KEY`, `DB_*` 필수
2. 스키마 최신화
   - `alembic upgrade head`
3. 연결 확인
   - DB 연결 가능한지 확인
   - TourAPI 키 유효성 확인

### Step B. 목록 수집 (코스 ID 확보)

1. `areaBasedList2` 호출 시 `contentTypeId=25`로 페이지 순회
2. `content_id` 목록 수집
3. 중단/재시작 대비로 페이지 커서와 호출 수를 메타데이터에 기록

권장 메타:
- `current_page`, `total_pages`, `records_fetched`, `api_calls_used`

### Step C. 코스별 상세 수집 (RAW 저장)

각 `content_id`마다 상세 endpoint를 호출해 원본 JSON을 통합 저장합니다.

- 권장 endpoint 조합:
  - `detailCommon2`
  - `detailIntro2`
  - `detailInfo2` (하위 코스 아이템 파싱 핵심)
  - `detailImage2` (필요 시)
- `courses_raw_snapshots`에 `content_id` 기준 UPSERT
- RAW는 최신본만 유지

### Step D. `travel_courses` UPSERT

RAW에서 코어 필드를 파싱해 `travel_courses`에 UPSERT합니다.

핵심 필드:
- `content_id`, `title`, `overview`, `theme`
- `taketime`, `taketime_minutes`
- `distance`, `distance_km`
- `schedule`, `infocenter_tourcourse`, `first_image`
- `source_modified_time`, `created_time`, `synced_at`

권장 파싱 정책:
- 숫자 파싱 실패 시 `taketime_minutes`, `distance_km`는 `NULL` 허용
- 문자열 원문(`taketime`, `distance`)은 최대한 보존

### Step E. `course_items` REPLACE

`detailInfo2`에서 하위 코스 항목을 파싱해 `course_items`를 코스 단위로 교체합니다.

필수 규칙:
1. `BEGIN`
2. `DELETE FROM course_items WHERE course_content_id = :content_id`
3. 새 아이템 `INSERT` (serial 순서 보장)
4. `COMMIT`

컬럼 매핑 가이드:
- `course_content_id`: 상위 코스 `content_id`
- `serial_num`: 원본 순서
- `sub_content_id`: TourAPI 하위 콘텐츠 ID
- `matched_spot_id`: `spots_core` 매칭 성공 시만 값 입력, 실패 시 `NULL`
- `sub_name`, `sub_overview`, `sub_image`, `sub_image_alt`: fallback 표시용 원문 보존

### Step F. (선택) 임베딩 갱신

- `overview_hash`가 바뀐 코스만 `travel_course_embeddings` 재생성
- 초기에는 코어/아이템 적재 먼저 안정화한 뒤 붙이는 것을 권장

### Step G. 동기화 로그 마감

`sync_logs`에 다음을 남깁니다.
- `job_name`: `tourapi_courses_sync`
- `status`: `success`/`failed`
- `records_fetched`, `records_upserted`, `records_failed`, `api_calls_used`
- `metadata`: 페이지, 커서, 경고, 실패 샘플

---

## 3) 장애 없이 운영하려면 (실무 체크리스트)

### 체크 1. REPLACE 트랜잭션

- `course_items`는 반드시 코스 단위 단일 트랜잭션
- DELETE와 INSERT 분리 실행 금지

### 체크 2. 부분 실패 허용

- 코스 1건 실패가 전체 잡 실패로 번지지 않게 per-course 예외 처리
- 실패 건은 `sync_logs.metadata.errors[]`에 샘플 저장

### 체크 3. 재실행 안전성(idempotency)

- RAW/CORE는 UPSERT
- `course_items`는 REPLACE 패턴으로 반복 실행해도 동일 결과 보장

### 체크 4. 매칭 실패 허용

- `matched_spot_id`는 nullable 정책 유지
- 매칭 실패를 오류로 취급하지 않고 fallback 컬럼으로 UI 노출 가능하게 유지

---

## 4) 운영 검증 SQL

```sql
-- 1) 코스 적재 건수
SELECT COUNT(*) AS travel_courses_count
FROM travel_courses
WHERE is_active = true;

-- 2) 코스별 아이템 수 (상위 20개)
SELECT course_content_id, COUNT(*) AS item_count
FROM course_items
GROUP BY course_content_id
ORDER BY item_count DESC
LIMIT 20;

-- 3) RAW 누락 확인
SELECT tc.content_id
FROM travel_courses tc
LEFT JOIN courses_raw_snapshots crs ON crs.content_id = tc.content_id
WHERE crs.content_id IS NULL
LIMIT 50;

-- 4) 최근 동기화 로그 확인
SELECT id, job_name, status, started_at, ended_at, records_fetched, records_upserted, records_failed
FROM sync_logs
WHERE job_name = 'tourapi_courses_sync'
ORDER BY id DESC
LIMIT 20;
```

---

## 5) 구현/운영 권장 전략

1. **1차 목표**: `courses_raw_snapshots` + `travel_courses` + `course_items` 안정화
2. **2차 목표**: `matched_spot_id` 품질 개선(매칭 로직 고도화)
3. **3차 목표**: `travel_course_embeddings` 연동

처음부터 모든 파생 처리(LLM/임베딩)를 한 번에 붙이기보다, 코스 본체 적재를 먼저 안정화하는 접근이 운영 리스크가 가장 낮습니다.


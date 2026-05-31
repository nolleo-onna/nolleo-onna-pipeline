# TourAPI 여행코스(ContentTypeId=25) 적재 가이드

현재 Alembic 기준 공식 여행코스 도메인은 사용자가 생성한 추천 코스가 아니라
TourAPI가 제공하는 공식 여행코스 마스터입니다.

## 1. 대상 테이블

- `travel_courses`: 공식 여행코스 마스터
- `travel_course_raw_snapshots`: 원천 응답 JSONB 최신본
- `course_items`: `detailInfo2` 하위 방문지 목록
- `spots`: 하위 방문지가 TourAPI 스팟과 매칭될 때 참조

`content_id`, `course_content_id`, `sub_content_id`, `matched_spot_id`는 TourAPI 자연키이므로
`VARCHAR(20)` 기준을 유지합니다.

## 2. 적재 순서

1. `areaBasedList2`를 `contentTypeId=25`로 호출해 코스 `content_id` 목록을 확보합니다.
2. 각 코스별로 `detailCommon2`, `detailIntro2`, `detailInfo2`, 필요 시 `detailImage2`를 호출합니다.
3. 원천 응답을 `travel_course_raw_snapshots`에 UPSERT합니다.
4. 코어 필드를 파싱해 `travel_courses`에 UPSERT합니다.
5. `detailInfo2` 하위 방문지는 코스 단위로 `course_items`를 REPLACE합니다.

`course_items`는 반드시 단일 트랜잭션에서 처리합니다.

```sql
BEGIN;
DELETE FROM course_items WHERE course_content_id = :content_id;
-- 새 아이템 INSERT
COMMIT;
```

## 3. 주요 컬럼 매핑

- `travel_courses.content_id`: TourAPI 코스 contentid
- `travel_courses.title`: 코스명
- `travel_courses.overview`: 소개 원문
- `travel_courses.overview_hash`: 소개 변경 감지 해시
- `travel_courses.taketime`, `taketime_minutes`: 원문/파싱된 소요시간
- `travel_courses.distance`, `distance_km`: 원문/파싱된 거리
- `travel_courses.source_created_at`: TourAPI 원천 생성 시각
- `travel_courses.source_modified_time`: TourAPI 원천 수정 시각
- `course_items.course_content_id`: 상위 공식 코스 content_id
- `course_items.sub_content_id`: 원천 하위 콘텐츠 ID
- `course_items.matched_spot_id`: `spots.content_id` 매칭 성공 시만 입력

매칭 실패는 오류가 아닙니다. `matched_spot_id`는 nullable이며, `sub_name`,
`sub_overview`, `sub_image`를 fallback 표시용으로 보존합니다.

## 4. 운영 검증 SQL

```sql
SELECT COUNT(*) AS travel_courses_count
FROM travel_courses
WHERE is_active = true;

SELECT course_content_id, COUNT(*) AS item_count
FROM course_items
GROUP BY course_content_id
ORDER BY item_count DESC
LIMIT 20;

SELECT tc.content_id
FROM travel_courses tc
LEFT JOIN travel_course_raw_snapshots raw ON raw.content_id = tc.content_id
WHERE raw.content_id IS NULL
LIMIT 50;

SELECT id, job_name, status, started_at, ended_at, records_fetched,
       records_upserted, records_failed
FROM sync_logs
WHERE job_name = 'tourapi_courses_sync'
ORDER BY id DESC
LIMIT 20;
```

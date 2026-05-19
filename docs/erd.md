# 놀러온나 — 데이터베이스 ERD

> 정규화된 30+ 테이블 ERD. 도메인별로 그룹화되어 있음.
> 표 + 머메이드 코드 모두 포함.

---

## 도메인 구성 한눈에


| 도메인         | 테이블                                                                                                              | 책임              |
| ----------- | ---------------------------------------------------------------------------------------------------------------- | --------------- |
| 사용자         | USERS, USER_EMBEDDINGS                                                                                           | 인증, 취향 벡터       |
| 북마크/리뷰      | BOOKMARKS, BOOKMARK_COLLECTIONS, USER_REVIEWS, VISIT_HISTORY, NOTIFICATIONS                                      | 사용자 활동          |
| 코스 (사용자 생성) | GENERATED_COURSES, GENERATED_COURSE_ITEMS, COURSE_DECISIONS                                                      | AI 추천 코스        |
| 콘텐츠 (한끗)    | HANKKUT, HANKKUT_SPOTS, HANKKUT_TAGS, HANKKUT_EVENTS                                                             | 큐레이션 콘텐츠        |
| 스팟 (마스터)    | SPOTS_CORE, SPOT_DETAILS, SPOT_EMBEDDINGS, SPOTS_RAW_SNAPSHOTS, SPOT_IMAGES, SPOT_TAGS, SPOT_CONGESTION_FORECAST | TourAPI 관광지     |
| 행사 (마스터)    | EVENTS_CORE, EVENT_DETAILS, EVENT_EMBEDDINGS, EVENTS_RAW_SNAPSHOTS, EVENT_IMAGES                                 | TourAPI 행사      |
| 공식 코스 (마스터) | TRAVEL_COURSES, TRAVEL_COURSE_EMBEDDINGS, COURSES_RAW_SNAPSHOTS, COURSE_ITEMS                                    | TourAPI 여행코스    |
| 착한가격        | GOOD_PRICE_SHOPS, GOOD_PRICE_MATCH_QUEUE, GOOD_PRICE_SHOP_PRICES, GOOD_PRICE_PRICE_OBSERVATIONS, GPS_RAW_SNAPSHOTS, GOOD_PRICE_LOCALE_CODES | 부산 가성비 매장       |
| 검수 큐        | BUSINESS_HOURS_REVIEW_QUEUE                                                                                      | LLM 신뢰도         |
| 태그          | TAGS                                                                                                             | 통제어휘 + 자유태그 마스터 |
| 코드/날씨·대기질 마스터 | LDONG_CODES, LCLS_SYSTM_CODES, WEATHER_GRIDS, WEATHER_CACHE, AIR_QUALITY_STATIONS, AIR_QUALITY_CACHE (DDL 예정) | 지역/분류/날씨/미세먼지 |
| 운영          | SYNC_LOGS                                                                                                        | 파이프라인 추적        |


---

## 핵심 설계 패턴

### 1. Hot/Cold 분리 (1:1)

- `SPOTS_CORE` (hot, 슬림) ↔ `SPOT_DETAILS` (cold, 무거운 텍스트)
- `EVENTS_CORE` ↔ `EVENT_DETAILS`
- 핫 패스 쿼리에서 무거운 컬럼 안 읽도록 최적화

### 2. RAW 보관 → 정제 적재 → 임베딩

- `*_RAW_SNAPSHOTS` (외부 API 원본 JSONB) — 복구 안전망
- `*_CORE` / `*_DETAILS` (정제된 정규화 데이터)
- `*_EMBEDDINGS` (vector(1536), HNSW 인덱스)

### 3. 변경 감지 해시

- `overview_hash`로 LLM 재호출 최소화
- hash 같으면 summary/embedding/tags 재처리 skip

### 4. 신뢰도 큐 패턴

- LLM 자동 처리 (≥0.85 confidence) → 즉시 적용
- 중간 신뢰도 (0.7~0.85) → 큐잉, 24h SLA
- 낮은 신뢰도 (<0.7) → 큐잉 + UI에 "확인 필요" 명시
- 모든 LLM 산출물에 `model_name`, `model_version`, `prompt_version` 추적

### 5. PostGIS Generated Column

```sql
geog geography(POINT, 4326) GENERATED ALWAYS AS
  (ST_SetSRID(ST_MakePoint(map_x, map_y), 4326)::geography) STORED
```

### 6. Soft Delete vs Hard Delete 정책

- **Soft Delete** (`deleted_at`): USERS, GENERATED_COURSES, USER_REVIEWS, HANKKUT
- **Hard Delete**: BOOKMARKS, NOTIFICATIONS (이력 보존 가치 낮음)
- **is_active 플래그**: SPOTS_CORE, EVENTS_CORE, TRAVEL_COURSES, GOOD_PRICE_SHOPS (외부 API 사라지면 비활성화, 보관)

### 7. 시간대 정책 (반드시 준수)

- DB 서버: UTC
- TIMESTAMPTZ: UTC 자동 저장
- `business_hours` JSONB의 시간 문자열: KST 기준 ("09:00")
- `base_ymd` 등 DATE: KST 날짜 기준
- 비교 시: `AT TIME ZONE 'Asia/Seoul'` 명시
- 사용자 표시: 앱 레이어에서 KST 변환

---

## Mermaid ERD 코드

```mermaid
---
config:
  layout: elk
---
erDiagram
    direction TB
    USERS {
        bigserial id PK "내부ID"
        varchar external_id "소셜로그인ID"
        varchar provider "kakao_naver_google"
        varchar email "이메일_알림용"
        varchar nickname "닉네임"
        text profile_image_url "프로필이미지"
        varchar role "user_admin"
        timestamp created_at "가입시각"
        timestamp last_active_at "최근접속"
        timestamp deleted_at "탈퇴시각_softdelete"
    }

    USER_EMBEDDINGS {
        bigint user_id PK,FK "사용자ID_FK"
        vector taste_embedding "취향벡터"
        varchar model_name "모델명"
        varchar model_version "버전"
        integer activity_count "반영활동수"
        timestamp embedded_at "생성시각"
        timestamp updated_at "갱신시각"
    }

    BOOKMARKS {
        bigserial id PK "내부ID"
        bigint user_id FK "사용자ID"
        varchar spot_content_id FK "스팟_nullable"
        bigint generated_course_id FK "코스_nullable"
        varchar event_content_id FK "행사_nullable"
        bigint hankkut_id FK "한끗_nullable"
        bigint collection_id FK "컬렉션FK_NOTNULL"
        text note "메모_nullable"
        timestamp created_at "저장시각"
    }

    BOOKMARK_COLLECTIONS {
        bigserial id PK "내부ID"
        bigint user_id FK "사용자ID"
        varchar name "컬렉션명"
        varchar collection_type "default_wishlist_custom"
        smallint bookmark_count "캐시카운트"
        timestamp created_at "생성시각"
    }

    GENERATED_COURSES {
        bigserial id PK "내부ID"
        bigint user_id FK "생성자_NOTNULL"
        bigint parent_course_id FK "재추천원본_nullable"
        uuid pair_id "형제코스묶음"
        varchar weight_profile "balanced_budget"
        varchar title "코스명"
        varchar input_signgu "입력지역"
        integer input_budget "입력예산"
        varchar input_duration "입력시간"
        varchar input_companion "입력동행"
        text_array input_mood "입력분위기"
        varchar generation_mode "taste_novelty_default"
        varchar generation_method "natural_form_recommend"
        integer total_cost "총비용"
        integer total_minutes "총시간"
        integer total_savings "절약금액"
        varchar compared_with_travel_course_id FK "공식코스비교기준_nullable"
        jsonb weather_at_gen "날씨스냅샷"
        boolean is_public "공개여부_default_false"
        varchar share_token UK "공유URL토큰"
        integer view_count "조회수"
        timestamp created_at "생성시각"
        timestamp updated_at "수정시각"
        timestamp deleted_at "삭제시각_softdelete"
    }

    GENERATED_COURSE_ITEMS {
        bigserial id PK "내부ID"
        bigint course_id FK "코스ID"
        smallint serial_num "방문순서"
        varchar spot_content_id FK "스팟ID"
        time arrival_time "예상도착시각"
        smallint duration_minutes "체류시간_분"
        integer expected_cost "예상비용"
        smallint travel_minutes_from_prev "이전스팟이동시간"
        text notes "타임라인노트"
    }

    USER_REVIEWS {
        bigserial id PK "내부ID"
        bigint user_id FK "작성자ID_nullable_익명화"
        varchar spot_content_id FK "스팟ID"
        text content "한줄리뷰_500자제한"
        smallint rating "별점1_5"
        timestamp created_at "작성시각"
        timestamp updated_at "수정시각"
        timestamp deleted_at "삭제시각_softdelete"
    }

    VISIT_HISTORY {
        bigserial id PK "내부ID"
        bigint user_id FK "사용자ID"
        varchar spot_content_id FK "스팟ID"
        date first_visited_at "첫방문일"
        date last_visited_at "최근방문일"
        smallint visit_count "방문횟수"
        varchar with_companion "동행유형_nullable"
        text note "최근메모_nullable"
        timestamp created_at "최초기록시각"
        timestamp updated_at "갱신시각"
    }

    NOTIFICATIONS {
        bigserial id PK "내부ID"
        bigint user_id FK "수신자"
        varchar type "알림유형"
        varchar title "제목"
        text body "내용"
        varchar target_url "딥링크"
        boolean is_read "읽음여부"
        timestamp created_at "발송시각"
        timestamp read_at "읽은시각"
    }

    COURSE_DECISIONS {
        bigserial id PK "내부ID"
        bigint course_id FK "코스ID"
        varchar decision_type "exclude_replace_boost"
        varchar severity "critical_warning_info"
        varchar spot_content_id FK "원본후보스팟"
        varchar replacement_spot_id "대체결과스팟"
        text reason "개발자용사유"
        text user_message "UI표시용메시지"
        jsonb evidence "근거데이터JSONB"
        timestamp created_at "결정시각"
    }

    SPOTS_CORE {
        varchar content_id PK "콘텐츠ID"
        varchar content_type_id "12_14_39"
        varchar title "이름"
        boolean source_tour_api "투어API출처"
        boolean source_busan_food "미식투어출처"
        numeric map_x "경도"
        numeric map_y "위도"
        geography geog "PostGIS_generated"
        varchar l_dong_regn_cd FK "시도코드"
        varchar l_dong_signgu_cd FK "시군구코드"
        varchar lcls_systm_1 "대분류"
        varchar lcls_systm_2 "중분류"
        varchar lcls_systm_3 "소분류"
        text first_image "대표이미지"
        text first_image2 "썸네일"
        text overview_summary "LLM요약"
        smallint price_level "가격대0_3"
        varchar price_text "가격표시"
        boolean indoor "실내여부"
        boolean is_good_price "가성비매칭_플래그캐시"
        numeric today_concentration_rate "오늘혼잡도_캐시"
        numeric upcoming_concentration_avg "향후3일평균_캐시"
        timestamp concentration_updated_at "혼잡도갱신"
        numeric trend_score "트렌드점수"
        numeric gem_score "갈타이밍점수"
        timestamp trend_updated_at "트렌드갱신"
        numeric popularity_score "인기도"
        numeric avg_rating "평균별점_캐시"
        integer review_count "리뷰수_캐시"
        timestamp rating_updated_at "별점갱신시각"
        timestamp source_modified_time "API수정일"
        timestamp synced_at "동기화시각"
        timestamp updated_at "갱신시각"
        boolean is_active "활성여부"
        timestamp inactive_since "비활성시점"
    }

    HANKKUT {
        bigserial id PK "내부ID"
        varchar title "제목"
        varchar category "event_free_transport_tip"
        text content "본문_3000자제한"
        text cover_image_url "커버이미지"
        bigint author_user_id FK "작성자_admin전용"
        varchar status "pending_approved_rejected_archived"
        varchar source "manual_auto_event"
        date valid_from "유효시작일"
        date valid_until "유효종료일_시즌한정"
        timestamp published_at "공개시각"
        integer view_count "조회수"
        timestamp created_at "작성시각"
        timestamp updated_at "수정시각"
        timestamp deleted_at "삭제시각_softdelete"
    }

    HANKKUT_SPOTS {
        bigint hankkut_id PK,FK "한끗ID_FK"
        varchar spot_content_id PK,FK "스팟ID_FK"
        smallint display_order "노출순서"
        timestamp created_at "연결시각"
    }

    HANKKUT_TAGS {
        bigint hankkut_id PK,FK "한끗ID_FK"
        smallint tag_id PK,FK "태그ID_FK"
        timestamp created_at "부착시각"
    }

    HANKKUT_EVENTS {
        bigint hankkut_id PK,FK "한끗ID_FK"
        varchar event_content_id PK,FK "행사ID_FK"
        smallint display_order "노출순서_1부터_UK"
        timestamp created_at "연결시각"
    }

    EVENTS_CORE {
        varchar content_id PK "콘텐츠ID"
        varchar title "행사명"
        numeric map_x "경도"
        numeric map_y "위도"
        geography geog "PostGIS_generated"
        varchar l_dong_regn_cd FK "시도코드"
        varchar l_dong_signgu_cd FK "시군구코드"
        text first_image "대표이미지"
        text first_image2 "썸네일"
        date event_start_date "시작일"
        date event_end_date "종료일"
        daterange event_period "기간_generated_GiST"
        text event_place "장소"
        varchar festival_grade "축제등급"
        varchar venue_spot_id FK "행사장_매칭실패NULL"
        text overview_summary "LLM요약"
        boolean indoor "실내여부_LLM추정"
        numeric expected_concentration "예상혼잡도_자체파생"
        varchar expected_concentration_source "rule_llm_manual"
        timestamp source_modified_time "API수정일"
        timestamp synced_at "동기화시각"
        timestamp updated_at "갱신시각"
        boolean is_active "활성여부"
        timestamp inactive_since "비활성시점"
    }

    EVENT_DETAILS {
        varchar content_id PK,FK "행사ID_FK"
        text addr1 "기본주소"
        text addr2 "상세주소"
        varchar tel "전화"
        text homepage "홈페이지"
        text overview "소개원문"
        varchar overview_hash "변경감지해시"
        varchar play_time "공연시간_TourAPI원본"
        text use_time_festival "이용요금"
        varchar age_limit "관람연령"
        varchar booking_place "예매처"
        text program "프로그램"
        text sub_event "부대행사"
        varchar sponsor1 "주최자"
        varchar sponsor1_tel "주최연락처"
        varchar sponsor2 "주관사"
        varchar sponsor2_tel "주관연락처"
        varchar spendtime_festival "소요시간"
        text place_info "위치안내"
        text discount_info "할인정보"
        timestamp created_time "API생성일"
        timestamp updated_at "갱신시각"
    }

    BUSINESS_HOURS_REVIEW_QUEUE {
        bigserial id PK "내부ID"
        varchar content_id FK "스팟ID"
        text source_text "원본텍스트"
        varchar source_text_hash "원본해시_동일성검증"
        jsonb parsed_json "LLM파싱결과_표준스키마"
        numeric confidence "LLM자신감_0_1"
        boolean validation_passed "룰검증_재구성검증통과"
        varchar model_name "LLM모델명"
        varchar model_version "LLM모델버전"
        varchar prompt_version "프롬프트버전"
        bigint reviewed_by FK "검수자_admin"
        timestamp reviewed_at "검수시각"
        varchar review_status "pending_approved_rejected"
        text reviewer_note "검수자메모"
        timestamp created_at "큐등록시각"
    }

    SPOT_DETAILS {
        varchar content_id PK,FK "스팟ID_FK"
        varchar tel "전화번호"
        text homepage "홈페이지"
        text addr1 "기본주소"
        text addr2 "상세주소"
        varchar zipcode "우편번호"
        text overview "소개원문"
        varchar overview_hash "변경감지해시"
        jsonb intro "TourAPI운영정보_원본형태"
        jsonb business_hours "정규화영업시간_진실의원천"
        varchar business_hours_source "tourapi_raw_llm_auto_llm_verified_manual"
        numeric business_hours_confidence "LLM신뢰도_0_1"
        varchar business_hours_model "LLM모델추적"
        timestamp business_hours_parsed_at "정규화시각"
        timestamp business_hours_verified_at "관리자검수완료시각"
        timestamp business_hours_stale_after "갱신필요표시기준"
        boolean parking_available "주차가능"
        timestamp created_time "API생성일"
        timestamp updated_at "갱신시각"
    }

    SPOT_EMBEDDINGS {
        varchar content_id PK,FK "스팟ID_FK"
        vector embedding "단일임베딩_제목태그overview"
        text source_text "임베딩입력텍스트"
        varchar source_hash "변경감지해시"
        varchar model_name "OpenAI모델명"
        varchar model_version "모델버전"
        integer token_count "토큰수_비용추적"
        timestamp embedded_at "임베딩생성시각"
        timestamp updated_at "row갱신시각"
    }

    SPOTS_RAW_SNAPSHOTS {
        varchar content_id PK,FK "스팟ID_FK"
        jsonb raw_json "엔드포인트별통합_endpoints키"
        timestamp fetched_at "최근수집시각"
        timestamp updated_at "row갱신시각"
    }

    SPOT_IMAGES {
        bigserial id PK "내부ID"
        varchar content_id FK "스팟ID"
        text origin_img_url "원본URL"
        text small_img_url "썸네일"
        varchar img_name "이미지설명"
        varchar serial_num "순서"
    }

    SPOT_TAGS {
        varchar content_id PK,FK "스팟ID_FK"
        smallint tag_id PK,FK "태그ID_FK"
        numeric score "확신도"
        varchar source "llm_rule_manual"
        timestamp created_at "부착시각"
    }

    SPOT_CONGESTION_FORECAST {
        bigserial id PK "내부ID"
        varchar content_id FK "스팟ID_매칭실패시NULL_UK_notnull_part"
        varchar area_cd "areaCd_시도코드"
        varchar signgu_cd FK "signguCd_LDONG참조_UK_null_part"
        varchar raw_tats_name "tAtsNm_TourAPI원본관광지명_UK_null_part"
        varchar area_name "areaNm_시도명"
        varchar signgu_name "signguNm_시군구명"
        date base_ymd "baseYmd_예측기준일_UK_both_parts"
        numeric concentration_rate "cnctrRate_TourAPI원본"
        smallint level "자체등급1_5_파생"
        varchar source "tourapi_llm_rule_UK_both_parts"
        timestamp fetched_at "수집시각"
    }

    GOOD_PRICE_SHOPS {
        bigserial id PK "내부ID"
        varchar external_id UK "idx_API업체번호"
        varchar name "sj_업소명"
        varchar owner_name "mNm_대표자"
        text addr "adres_주소"
        varchar tel "tel_전화"
        varchar category_code "cnCd_602음식점603이미용604목욕"
        varchar category_name "cn_업소구분"
        varchar locale_code FK "localeCd_동코드"
        varchar locale_name "locale_동명"
        varchar l_dong_signgu_cd FK "시군구파생"
        text intro_html "intrcn_HTML원본"
        text intro_text "정제텍스트"
        varchar business_hours_raw "bsnTime_TourAPI원본"
        jsonb business_hours_parsed "정규화_룰우선LLM실패시"
        boolean has_parking "parkngAt_Y_N"
        text img_file1 "imgFile1_이미지1URL"
        varchar img_name1 "이미지1명"
        text img_file2 "imgFile2_이미지2URL"
        varchar img_name2 "이미지2명"
        numeric map_x "경도_지오코딩결과"
        numeric map_y "위도_지오코딩결과"
        geography geog "PostGIS_generated"
        timestamp geocoded_at "지오코딩성공시각"
        varchar geocoded_source "kakao_naver"
        boolean geocode_failed "지오코딩실패"
        varchar match_status "pending_matched_unmatched_separate"
        varchar matched_spot_id FK "매칭된SPOTS_CORE_nullable_SoT단방향"
        timestamp source_created_at "creatDt_API생성일파싱"
        timestamp synced_at "동기화시각"
        timestamp updated_at "갱신시각"
        boolean is_active "활성여부"
        timestamp inactive_since "비활성시점"
    }

    GOOD_PRICE_MATCH_QUEUE {
        bigserial id PK "내부ID"
        bigint shop_id FK "착한가격업소ID"
        varchar candidate_spot_id FK "후보스팟ID"
        numeric match_score "총점0_1"
        numeric phone_score "전화번호점수"
        numeric name_score "이름유사도점수"
        numeric address_score "주소유사도점수"
        numeric distance_m "직선거리미터"
        jsonb signal_details "신호별상세JSONB"
        varchar match_status "pending_approved_rejected"
        bigint reviewed_by FK "검수자_admin"
        timestamp reviewed_at "검수시각"
        text reviewer_note "검수메모"
        timestamp created_at "큐등록시각"
    }

    GOOD_PRICE_SHOP_PRICES {
        bigserial id PK "내부ID"
        bigint shop_id FK "착한가격업소ID"
        varchar item_name "기준품목명"
        numeric current_price "현재확정가격"
        varchar currency "통화코드_KRW"
        varchar unit "단위_1인분_세트_회"
        timestamp last_observed_at "마지막관측시각"
        timestamp last_verified_at "마지막검수시각"
        bigint current_price_observation_id FK "근거관측ID_nullable"
        timestamp updated_at "갱신시각"
    }

    GOOD_PRICE_PRICE_OBSERVATIONS {
        bigserial id PK "내부ID"
        bigint shop_id FK "착한가격업소ID"
        varchar source_type "admin_manual_user_report_crawler"
        bigint submitter_user_id FK "제보자_nullable_admin수기면NULL"
        varchar item_name "제보품목명"
        numeric reported_price "제보가격"
        varchar currency "통화코드_KRW"
        varchar unit "단위_1인분_세트_회"
        timestamp observed_at "가격확인시각"
        varchar evidence_type "receipt_photo_text_none"
        text evidence_ref "증빙URL_파일키_텍스트"
        varchar report_status "pending_approved_rejected"
        bigint reviewed_by FK "검수자_admin"
        timestamp reviewed_at "검수시각"
        text reviewer_note "검수메모"
        jsonb raw_payload "원본JSONB_확장대비"
        timestamp created_at "제보등록시각"
    }

    TAGS {
        smallserial tag_id PK "태그ID"
        varchar tag_name UK "태그명"
        varchar tag_type "controlled_free"
        varchar category "카테고리10종"
        vector embedding "태그임베딩_유사도검색"
        smallint canonical_tag_id "정규태그ID_동의어매핑"
        varchar model_name "임베딩모델명"
        varchar model_version "모델버전"
        integer usage_count "사용수_캐시"
        boolean is_active "활성"
        timestamp embedded_at "임베딩생성시각"
        timestamp created_at "등록시각"
    }

    EVENTS_RAW_SNAPSHOTS {
        varchar content_id PK,FK "행사ID_FK"
        jsonb raw_json "엔드포인트별통합_endpoints키"
        timestamp fetched_at "최근수집시각"
        timestamp updated_at "row갱신시각"
    }

    EVENT_IMAGES {
        bigserial id PK "내부ID"
        varchar content_id FK "행사ID"
        text origin_img_url "원본"
        text small_img_url "썸네일"
        varchar img_name "설명"
        varchar serial_num "순서"
    }

    EVENT_EMBEDDINGS {
        varchar content_id PK,FK "행사ID_FK"
        vector embedding "단일임베딩_제목program_overview"
        text source_text "임베딩입력텍스트"
        varchar source_hash "변경감지해시"
        varchar model_name "OpenAI모델명"
        varchar model_version "모델버전"
        integer token_count "토큰수_비용추적"
        timestamp embedded_at "임베딩생성시각"
        timestamp updated_at "row갱신시각"
    }

    TRAVEL_COURSES {
        varchar content_id PK "콘텐츠ID"
        varchar title "코스명"
        text overview "소개원문"
        varchar overview_hash "변경감지해시"
        text overview_summary "LLM요약"
        varchar theme "테마_TourAPI원본"
        varchar taketime "소요시간_TourAPI원본"
        integer taketime_minutes "분단위_파싱본"
        varchar distance "거리_TourAPI원본"
        numeric distance_km "km단위_파싱본"
        text schedule "일정"
        varchar infocenter_tourcourse "문의처"
        text first_image "대표이미지"
        varchar l_dong_regn_cd FK "시도코드"
        timestamp source_modified_time "API수정일"
        timestamp created_time "API생성일"
        timestamp synced_at "동기화시각"
        timestamp updated_at "갱신시각"
        boolean is_active "활성여부"
        timestamp inactive_since "비활성시점"
    }

    TRAVEL_COURSE_EMBEDDINGS {
        varchar content_id PK,FK "코스ID_FK"
        vector embedding "단일임베딩_제목theme_overview"
        text source_text "임베딩입력텍스트"
        varchar source_hash "변경감지해시"
        varchar model_name "OpenAI모델명"
        varchar model_version "모델버전"
        integer token_count "토큰수_비용추적"
        timestamp embedded_at "임베딩생성시각"
        timestamp updated_at "row갱신시각"
    }

    COURSES_RAW_SNAPSHOTS {
        varchar content_id PK,FK "코스ID_FK"
        jsonb raw_json "엔드포인트별통합_endpoints키"
        timestamp fetched_at "최근수집시각"
        timestamp updated_at "row갱신시각"
    }

    COURSE_ITEMS {
        bigserial id PK "내부ID"
        varchar course_content_id FK "상위코스"
        integer serial_num "방문순서"
        varchar sub_content_id "원본하위ID"
        varchar matched_spot_id FK "스팟매칭"
        varchar sub_name "하위이름"
        text sub_overview "하위설명"
        text sub_image "하위이미지"
        text sub_image_alt "대체텍스트"
    }

    GPS_RAW_SNAPSHOTS {
        bigint shop_id PK,FK "업소ID_FK"
        jsonb raw_json "엔드포인트별통합_endpoints키"
        timestamp fetched_at "최근수집시각"
        timestamp updated_at "row갱신시각"
    }

    GOOD_PRICE_LOCALE_CODES {
        varchar locale_cd PK "동코드"
        varchar locale_name "동명"
        varchar signgu_cd FK "시군구코드"
        varchar signgu_name "시군구명"
    }

    LDONG_CODES {
        varchar regn_cd PK "시도코드"
        varchar signgu_cd PK "시군구코드"
        varchar name "한글명"
    }

    WEATHER_GRIDS {
        varchar signgu_cd PK "시군구코드"
        varchar signgu_name "구군명"
        numeric center_lat "중심위도"
        numeric center_lon "중심경도"
        integer kma_nx "격자X"
        integer kma_ny "격자Y"
    }

    LCLS_SYSTM_CODES {
        varchar code1 PK "대분류"
        varchar code2 PK "중분류"
        varchar code3 PK "소분류"
        varchar name "한글분류명"
    }

    WEATHER_CACHE {
        bigserial id PK "내부ID"
        varchar signgu_cd FK "시군구코드"
        timestamp observed_at "예보시각"
        integer rain_prob "강수확률"
        numeric temperature "기온"
        varchar sky_condition "하늘상태"
        varchar pty "강수형태"
        timestamp fetched_at "호출시각"
        timestamp expires_at "만료시각"
    }

    AIR_QUALITY_STATIONS {
        varchar regn_cd "시도26"
        varchar signgu_cd PK "시군구3자리"
        varchar station_name UK "에어코리아측정소명"
    }

    AIR_QUALITY_CACHE {
        bigserial id PK "내부ID"
        varchar signgu_cd FK "시군구"
        timestamp observed_at "측정또는예보시각"
        varchar record_kind "realtime_forecast"
        varchar inform_code "PM10_PM25_O3"
        numeric pm10_value "미세먼지농도"
        numeric pm25_value "초미세먼지농도"
        varchar pm10_grade "등급"
        varchar pm25_grade "등급"
        text forecast_overall "예보개황"
        text forecast_cause "발생원인"
        timestamp fetched_at "호출시각"
        timestamp expires_at "만료시각"
    }

    SYNC_LOGS {
        bigserial id PK "내부ID"
        varchar job_name "잡이름"
        varchar run_type "scheduled_manual_triggered_regression"
        varchar status "running_success_failed_partial_cancelled"
        bigint triggered_by FK "수동실행자_admin"
        bigint parent_run_id FK "부모job_chain추적"
        timestamp started_at "시작시각"
        timestamp ended_at "종료시각_running중NULL"
        integer duration_seconds "실행시간_파생"
        integer api_calls_used "외부API호출수_쿼터추적"
        integer records_fetched "조회수"
        integer records_upserted "반영수"
        integer records_failed "실패수"
        text error_message "실패시에러"
        jsonb metadata "job별상세JSONB"
    }

    USERS ||--o| USER_EMBEDDINGS : "취향벡터 1:1"
    USERS ||--o{ BOOKMARKS : "북마크"
    USERS ||--o{ BOOKMARK_COLLECTIONS : "컬렉션 소유"
    USERS ||--o{ GENERATED_COURSES : "생성한 코스"
    USERS ||--o{ USER_REVIEWS : "작성 리뷰"
    USERS ||--o{ VISIT_HISTORY : "방문 기록"
    USERS ||--o{ NOTIFICATIONS : "알림 수신"
    BOOKMARK_COLLECTIONS ||--o{ BOOKMARKS : "폴더 그룹"
    BOOKMARKS }o--o| SPOTS_CORE : "스팟 북마크"
    BOOKMARKS }o--o| GENERATED_COURSES : "코스 북마크"
    BOOKMARKS }o--o| EVENTS_CORE : "행사 북마크"
    BOOKMARKS }o--o| HANKKUT : "한끗 북마크"
    GENERATED_COURSES ||--o{ GENERATED_COURSE_ITEMS : "코스 아이템"
    GENERATED_COURSES ||--o{ COURSE_DECISIONS : "의사결정 로그"
    GENERATED_COURSES ||--o{ GENERATED_COURSES : "재추천 부모자식"
    GENERATED_COURSES ||--o| GENERATED_COURSES : "형제 pair"
    GENERATED_COURSE_ITEMS }o--|| SPOTS_CORE : "스팟 연결"
    COURSE_DECISIONS }o--o| SPOTS_CORE : "관련 스팟"
    HANKKUT }o--|| USERS : "작성자_admin"
    HANKKUT ||--o{ HANKKUT_SPOTS : "관련 스팟 N:M"
    HANKKUT ||--o{ HANKKUT_TAGS : "태그 N:M"
    HANKKUT ||--o{ HANKKUT_EVENTS : "행사 N:M"
    HANKKUT_SPOTS }o--|| SPOTS_CORE : "스팟 연결"
    HANKKUT_TAGS }o--|| TAGS : "태그 연결"
    HANKKUT_EVENTS }o--|| EVENTS_CORE : "행사 연결"
    USER_REVIEWS }o--|| SPOTS_CORE : "리뷰 대상"
    SPOTS_CORE ||--o{ BUSINESS_HOURS_REVIEW_QUEUE : "검토 대기 이력"
    BUSINESS_HOURS_REVIEW_QUEUE }o--o| USERS : "검수자"
    SPOTS_CORE ||--o| SPOT_DETAILS : "1:1 상세"
    SPOTS_CORE ||--o| SPOT_EMBEDDINGS : "1:1 임베딩"
    SPOTS_CORE ||--o| SPOTS_RAW_SNAPSHOTS : "1:1 원본"
    SPOTS_CORE ||--o{ SPOT_IMAGES : "갤러리 N장"
    SPOTS_CORE ||--o{ SPOT_TAGS : "태그 매핑"
    SPOTS_CORE ||--o{ SPOT_CONGESTION_FORECAST : "집중률 예측"
    SPOTS_CORE ||--o{ VISIT_HISTORY : "방문 대상"
    TAGS ||--o{ SPOT_TAGS : "태그 사용"
    EVENTS_CORE ||--o| EVENT_DETAILS : "1:1 상세"
    EVENTS_CORE ||--o| EVENTS_RAW_SNAPSHOTS : "1:1 원본"
    EVENTS_CORE ||--o| EVENT_EMBEDDINGS : "1:1 임베딩"
    EVENTS_CORE ||--o{ EVENT_IMAGES : "이미지 N장"
    EVENTS_CORE }o--o| SPOTS_CORE : "행사장 연결"
    TRAVEL_COURSES ||--o| TRAVEL_COURSE_EMBEDDINGS : "1:1 임베딩"
    TRAVEL_COURSES ||--o| COURSES_RAW_SNAPSHOTS : "1:1 원본"
    TRAVEL_COURSES ||--o{ COURSE_ITEMS : "하위 스팟"
    TRAVEL_COURSES ||--o{ GENERATED_COURSES : "짠내 변환 원본"
    COURSE_ITEMS }o--o| SPOTS_CORE : "매칭 스팟"
    GOOD_PRICE_SHOPS ||--o| GPS_RAW_SNAPSHOTS : "1:1 원본"
    GOOD_PRICE_SHOPS ||--o{ GOOD_PRICE_MATCH_QUEUE : "매칭 후보"
    GOOD_PRICE_SHOPS ||--o{ GOOD_PRICE_SHOP_PRICES : "확정 가격"
    GOOD_PRICE_SHOPS ||--o{ GOOD_PRICE_PRICE_OBSERVATIONS : "가격 관측 이력"
    GOOD_PRICE_SHOPS }o--o| SPOTS_CORE : "매칭된 스팟_단방향"
    GOOD_PRICE_LOCALE_CODES ||--o{ GOOD_PRICE_SHOPS : "동 코드"
    GOOD_PRICE_MATCH_QUEUE }o--|| SPOTS_CORE : "후보 스팟"
    GOOD_PRICE_MATCH_QUEUE }o--o| USERS : "검수자"
    GOOD_PRICE_SHOP_PRICES }o--o| GOOD_PRICE_PRICE_OBSERVATIONS : "근거 관측"
    GOOD_PRICE_PRICE_OBSERVATIONS }o--o| USERS : "제보자"
    GOOD_PRICE_PRICE_OBSERVATIONS }o--o| USERS : "검수자"
    LDONG_CODES ||--o{ SPOTS_CORE : "법정동"
    LDONG_CODES ||--o{ EVENTS_CORE : "법정동"
    LDONG_CODES ||--o{ GOOD_PRICE_LOCALE_CODES : "시군구 상위"
    LDONG_CODES ||--o{ WEATHER_GRIDS : "시군구 매핑"
    LCLS_SYSTM_CODES ||--o{ SPOTS_CORE : "분류체계"
    WEATHER_GRIDS ||--o{ WEATHER_CACHE : "날씨 시계열"
    LDONG_CODES ||--o{ AIR_QUALITY_STATIONS : "구별측정소"
    AIR_QUALITY_STATIONS ||--o{ AIR_QUALITY_CACHE : "대기질 시계열"
```



---

## 주요 변경 이력

### 익명 사용자 제거 (확정)

- `GENERATED_COURSES.session_id` 컬럼 제거
- `saved_by_user_id` (nullable) → `user_id` (NOT NULL)
- 비로그인 코스 24시간 cron 정리 정책 폐기
- 비로그인은 콘텐츠 열람만 가능

### currently_open_cached 제거 (확정)

- `SPOTS_CORE.currently_open_cached`, `open_cache_updated_at` 제거
- 영업시간 SoT는 `SPOT_DETAILS.business_hours` JSONB 단일화
- `is_open_now()` stored function + Redis 응답 캐시로 일원화

### GOOD_PRICE_SHOPS ↔ SPOTS_CORE 단방향화 (확정)

- `SPOTS_CORE.good_price_shop_id` FK 제거
- `GOOD_PRICE_SHOPS.matched_spot_id` 단방향 FK만 유지
- `SPOTS_CORE.is_good_price` boolean 캐시는 유지

### 착한가격 가격모델 2층화 (확정)

- `GOOD_PRICE_SHOP_PRICES` 추가: 서비스 조회용 "현재 확정가" SoT
- `GOOD_PRICE_PRICE_OBSERVATIONS` 추가: 수기/유저 제보 append-only 이력 + 검수 상태
- 초기 운영은 `source_type='admin_manual'` 중심, 이후 `user_report`/`crawler` 확장

### 착한가격 가격 참조 단방향화 (1단계)

- 순환 참조 방지를 위해 `GOOD_PRICE_PRICE_OBSERVATIONS.shop_price_id` FK 미도입
- `GOOD_PRICE_SHOP_PRICES.current_price_observation_id` 단방향 참조만 유지

### USER_REVIEWS 익명화 보존

- `user_id` nullable 변경 + ON DELETE SET NULL
- 탈퇴 사용자 리뷰는 익명화 후 보존


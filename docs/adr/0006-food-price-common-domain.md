# ADR 0006 — 음식/가격 공통 도메인 모델

- 상태: Accepted
- 일자: 2026-05-31
- 적용 범위: `food_places`, `food_place_sources`, `food_place_menus`,
  `food_price_observations`, `food_place_spot_matches`, `spot_price_summary`

## Context

놀러온나의 핵심 차별점은 가격/예산 기반 추천이다. TourAPI의 음식점
(`contentTypeId=39`)만으로는 메뉴와 가격을 안정적으로 얻기 어렵고, 착한가격업소,
착한가격 메뉴 파일/API, RedTable, 부산맛집정보, 모범음식점, 운영자 수기 입력 등
여러 원천을 함께 써야 한다.

예전 설계의 `GOOD_PRICE_SHOPS`, `GOOD_PRICE_SHOP_PRICES`는 착한가격업소에 강하게
묶여 있어 다른 음식/가격 원천을 같은 모델로 흡수하기 어렵다.

## Decision

음식/가격 데이터는 착한가격 전용 모델이 아니라 공통 `food_*` 모델로 저장한다.

1. **장소 마스터 분리**
   - `food_places`는 외부 음식/가격 장소의 내부 마스터다.
   - 업소명, 업종, 주소, 전화번호, 영업시간 원문, 대표 메뉴, 좌표, 활성 상태를 보관한다.
   - 코스 식사 후보로 쓸 수 있는지는 `is_course_food_candidate`로 구분한다.

2. **원천 payload 보존**
   - `food_place_sources`에 원천 종류, 외부 ID, 지역, raw JSON, fetched_at을 저장한다.
   - 원천 종류는 `good_price_shop`, `good_price_menu`, `good_price_file`,
     `redtable`, `busan_food`, `model_restaurant`, `admin_manual`로 시작한다.

3. **현재 메뉴/가격과 관측 이력 분리**
   - `food_place_menus`는 서비스 조회용 현재 메뉴/가격이다.
   - `food_price_observations`는 API/file/admin/user/crawler 관측 이력과 검수 상태를 보관한다.
   - 승인된 관측만 현재 메뉴 가격 반영 대상으로 본다.

4. **TourAPI spots 매칭은 별도 테이블로 관리**
   - `food_place_spot_matches`가 `food_places`와 `spots`의 매칭을 담당한다.
   - `pending`, `matched`, `rejected`는 `spot_content_id NOT NULL`이어야 한다.
   - `separate`는 TourAPI 스팟과 연결하지 않고 별도 음식 장소로 둔다는 뜻이므로
     `spot_content_id IS NULL`이어야 한다.

5. **추천 조회 캐시는 SoT가 아니다**
   - `spot_price_summary`는 추천 쿼리 최적화용 캐시다.
   - source of truth는 `food_place_menus`와 `food_price_observations`다.

## Consequences

### Pros

- 착한가격업소뿐 아니라 다른 가격 원천을 같은 DB 모델로 수용할 수 있다.
- wide CSV(`품목1/가격1`, `품목2/가격2`)도 메뉴 row로 unpivot해 저장할 수 있다.
- 가격 현재값과 관측 이력이 분리되어 검수/감사 추적이 가능하다.
- TourAPI `spots`와 매칭되지 않는 음식 장소도 버리지 않고 보관할 수 있다.

### Cons / 주의

- 착한가격 전용 모델보다 적재 파서가 조금 더 복잡하다.
- source별 중복 장소 병합 정책이 필요하다.
- `spot_price_summary` 재계산 기준과 주기를 별도 운영해야 한다.

## Supersedes

- ADR 0002의 `GOOD_PRICE_SHOPS`, `GOOD_PRICE_SHOP_PRICES`,
  `GOOD_PRICE_PRICE_OBSERVATIONS` 중심 모델

## 관련 문서

- `docs/operation.md` 음식/가격 도메인
- `docs/erd.md` 음식/가격 ERD
- `alembic/versions/0007_create_food_price_domain.py`

# ADR 0002 — 착한가격 가격 데이터 모델: 확정가 + 관측이력 2계층

- 상태: Superseded by ADR 0006
- 일자: 2026-05-04
- 적용 범위: `GOOD_PRICE_SHOPS` 가격 운영, 수기 입력/유저 제보/향후 크롤러 적재, 코스 비용 계산(`GOOD_PRICE_SHOP_PRICES` 참조)

> 2026-05-31 스키마 리셋 이후 현재 DB는 `GOOD_PRICE_*` 테이블 대신
> `fd_food_places`, `fd_food_place_menus`, `fd_food_price_observations` 중심의 공통
> 음식/가격 모델을 사용한다. 현재 기준 결정은 ADR 0006을 따른다.

## Context

초기 운영은 크롤링 없이 운영자 수기 입력으로 시작하되, 곧 유저 제보와 자동 수집(crawler)까지
확장해야 한다. 단일 테이블에 현재가와 제보이력을 함께 넣으면 검수 상태, 감사 추적, 향후 소스
확장 시 충돌이 발생한다. 또한 `SPOT_CONGESTION_FORECAST`의 nullable key처럼, PostgreSQL의
`UNIQUE + NULL` 동작 차이로 중복 적재 갭이 생길 수 있어 키 정책도 명확히 해야 한다.

## Decision

가격 데이터는 2계층으로 분리하고, 1단계 운영 정책을 함께 고정한다.

1. **현재 확정가 SoT 분리**
   - 테이블: `GOOD_PRICE_SHOP_PRICES`
   - 역할: 서비스 조회/코스 비용 계산에서 읽는 단일 기준
   - 키: `(shop_id, item_name)` 유니크 업서트
   - 추적: `current_price_observation_id`로 근거 관측 연결

2. **관측이력(append-only) 분리**
   - 테이블: `GOOD_PRICE_PRICE_OBSERVATIONS`
   - 역할: 수기 입력 + 유저 제보 + 향후 crawler를 단일 스키마로 축적
   - 상태: `pending` / `approved` / `rejected`
   - 규칙: `approved`만 `GOOD_PRICE_SHOP_PRICES` 반영

3. **순환 참조 금지**
   - `GOOD_PRICE_SHOP_PRICES -> OBSERVATIONS` 단방향만 유지
   - `OBSERVATIONS -> SHOP_PRICES` 역참조 FK는 두지 않음

4. **1단계 권한/소유권**
   - Spring: 관측 입력/검수 및 확정가 반영 SoT
   - pipeline_user: `GOOD_PRICE_PRICE_OBSERVATIONS` 조회만 허용
   - crawler insert는 2단계부터 허용 (문서의 트리거 예시로 1단계 차단)

5. **NULL 갭 방지 키 정책**
   - `SPOT_CONGESTION_FORECAST`는 partial UK 2종 사용
     - `content_id IS NOT NULL`: `(content_id, base_ymd, source)`
     - `content_id IS NULL`: `(raw_tats_name, signgu_cd, base_ymd, source)`

## Consequences

### Pros
- 현재값 조회 성능과 이력 감사 추적을 동시에 확보
- 수기/유저/crawler 확장을 스키마 변경 없이 수용
- 권한과 상태전이 분리로 운영 사고(무단 반영, 중복 반영) 리스크 감소
- NULL 포함 중복 키 갭을 사전에 차단

### Cons / 주의
- 테이블/정책이 늘어 운영 복잡도 상승
- 승인 워크플로우를 지키지 않으면 현재값과 이력 불일치 가능
- 2단계(crawler 허용) 전환 시 권한/트리거를 반드시 함께 조정해야 함

### 비채택 대안
- **단일 가격 테이블**: 현재값/이력/검수 상태가 혼합되어 추적성과 확장성 저하
- **초기부터 경계 FK 전면 제거**: 초기 운영 안정성 저하, 검증 책임 급증
- **UNIQUE 단일키(content_id, base_ymd, source) 고수**: NULL 케이스 중복 적재 갭 잔존

## 관련 문서

- `docs/erd.md` 착한가격 도메인 (`GOOD_PRICE_SHOP_PRICES`, `GOOD_PRICE_PRICE_OBSERVATIONS`)
- `docs/erd.md` `SPOT_CONGESTION_FORECAST` partial UK 주석
- `docs/operation.md` §3 착한가격 도메인, `SPOT_CONGESTION_FORECAST` UPSERT UK 정책
- `docs/operation.md` §12 권한 분리 SQL, §13.6 상태 전이, §13.8 위반 감지

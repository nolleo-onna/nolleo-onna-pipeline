# ADR 0003 — SPOTS 비활성 처리 안전 가드: 4중 가드 + sync_started_at 컷오프

- 상태: Proposed
- 일자: 2026-05-07
- 적용 범위: SPOTS sync 잡의 `SPOTS_CORE.is_active` 비활성 전이 (TourAPI 관광지 ContentTypeId 12/14/39)

## Context

`docs/operation.md` §3 SPOTS_CORE에 "TourAPI에서 사라지면 `is_active=false` + `inactive_since=NOW()`" 정책은 있으나 **언제 비활성을 실행할지에 대한 안전 가드가 정의되어 있지 않다**. 그대로 구현하면 다음 위험이 있다.

- 부분 적재(예산 컷·페이지네이션 중단·일부 contentType 누락)가 비활성을 유발해 sync된 row만 살아남고 나머지가 통째로 비활성된다.
- TourAPI가 빈 응답을 정상 반환하는 부분 장애 케이스(에러 없음 + 페이지 다 돔)에서 활성 row 절반이 사라지는 false positive 가능.
- `docs/operation.md` §4 Q1/Q2/Q3 핫패스 인덱스가 모두 `WHERE is_active=true` partial index — 대량 비활성화 시 인덱스 갱신 비용이 핫패스 지연으로 전이.
- `source_tour_api=FALSE` 수기 등록 row가 TourAPI 회차에 의해 비활성되면 안 된다.

## Decision

비활성 SQL 실행 전 **4중 가드 + sync_started_at 컷오프 + source_tour_api 필터**로 보호한다.

1. **안전 가드 4종 (AND, 모두 통과 시에만 실행)**
   - `bootstrap_complete = True` — 모든 `contentTypeId`가 마지막 페이지까지 도달
   - `stopped_by_budget = False` — 예산 컷으로 중단되지 않음
   - `failure_rate < SPOTS_DEACTIVATE_MAX_FAILURE_RATE` (default `0.05`)
   - `deactivation_ratio < SPOTS_DEACTIVATE_MAX_RATIO` (default `0.2`) — dry-run 카운트로 활성 row 대비 비율 체크, 초과 시 ROLLBACK + skip
   - 임계값은 env로 빼서 코드 PR 없이 운영 튜닝 가능.

2. **대상 필터 (UPDATE WHERE 절)**
   - `l_dong_regn_cd / content_type_id` — **이번 회차가 실제로 풀스캔한 범위와 정확히 일치**해야 한다. 부분 region/contentType 회차로는 절대 비활성 미실행 (가드 1번이 글로벌 bootstrap 보장).
   - `source_tour_api = TRUE` — 수기 등록 row 보호.
   - `is_active = TRUE` — 멱등성 (이미 비활성 row는 UPDATE 미발생).
   - `synced_at < :sync_started_at` — 이번 회차에 갱신된 row 제외.

3. **재등장 복구는 `_upsert_core` ON CONFLICT에 위임**
   - 본 메서드는 "사라짐 감지 → 비활성"만 담당한다. 비활성 → 활성 전이 로직을 추가하지 않는다.
   - 단방향 책임 분리로 트랜잭션 경계와 단위 테스트가 단순해진다.

4. **비활성화 실패는 흡수, sync 잡 success 유지**
   - 가드 통과 후의 SQL 실패는 try/except로 잡고 metadata에만 기록. 비활성은 부수 작업이므로 핵심 적재 성공을 가리지 않는다.

5. **운영 가시성**
   - 비활성 카운트·skip 사유·실패율·비활성 비율을 `SYNC_LOGS.metadata`에 기록 (필드 정의는 `operation.md §3 SYNC_LOGS`에서 관리).

## Consequences

### Pros
- 부분 적재·API 부분 장애·수기 row·핫패스 인덱스 비용을 한 군데서 보호.
- skip 사유가 metadata로 자동 축적되어 임계값 재튜닝 근거가 된다.
- 시그니처 재사용성 — EVENTS_CORE / TRAVEL_COURSES / GOOD_PRICE_SHOPS 후속 PR에서 동일 가드 구조 적용 가능.

### Cons / 주의
- 4중 가드라 "왜 비활성이 안 일어나지?" 디버깅이 metadata `deactivation_skip_reason` 의존도에 묶인다.
- 임계값 `0.05 / 0.2`는 데이터 없이 정한 보수값 → 1개월 후 SYNC_LOGS 분포 보고 재튜닝.
- API가 영구적으로 죽어 응답이 안 오면 비율 가드에 막혀 자동 비활성이 영원히 안 일어난다 — 이 케이스는 운영자 수동 개입 영역.

### 비채택 대안
- **가드 없음**: 부분 장애·부분 적재에서 false positive로 활성 row 대량 손실 → 기각.
- **가드 1+2만 (bootstrap + budget)**: 빈 응답 정상 반환 케이스 미보호 → 기각.
- **하드 임계값**: 운영 튜닝 시 코드 PR 필요 → 기각.
- **재등장 복구 통합**: `_upsert_core` ON CONFLICT와 책임 중복 → 기각.

## 관련 문서

- `docs/operation.md` §1#1 TourAPI 관광지 적재 흐름
- `docs/operation.md` §3 SPOTS_CORE 비활성 처리
- `docs/operation.md` §3 SYNC_LOGS metadata 표준 필드 (본 ADR로 추가되는 필드 정의)
- `docs/operation.md` §4 Q1·Q2·Q3 partial index (`WHERE is_active=true`)
- `src/nolleo_pipeline/domains/spots/repository.py` `_upsert_core` ON CONFLICT
- `src/nolleo_pipeline/domains/spots/pipeline.py` `run_tourapi_spots_sync`
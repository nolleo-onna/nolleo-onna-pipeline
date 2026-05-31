# ADR 0005 — SPOT_CONGESTION_FORECAST Repository 정책 (UPSERT/매칭/캐시 갱신)

- 상태: Deferred
- 일자: 2026-05-07
- 적용 범위: `src/nolleo_pipeline/domains/congestion/repository.py`, `SPOT_CONGESTION_FORECAST`, `SPOTS_CORE` 혼잡도 캐시 컬럼

> 2026-05-31 Alembic 리셋에서는 `SPOT_CONGESTION_FORECAST`와 `spots` 혼잡도
> 캐시 컬럼을 제외했다. 본 정책은 후속 혼잡도 도메인 브랜치에서 재검토한다.

## Context

혼잡도 파이프라인은 스팟 본체와 달리 예측 시계열 데이터를 다룬다. 이때 아래 운영 이슈가 동시에 존재한다.

- `content_id` 매칭 실패를 허용해야 해서 nullable key를 포함한 UPSERT 설계가 필요하다.
- `SPOTS_CORE` 조회 핫패스 성능을 지키려면 혼잡도 캐시 갱신 범위를 최소화해야 한다.
- 이름 매칭은 완전 일치만으로는 false negative가 높고, 동명이 존재하면 비결정성이 생길 수 있다.
- 후속 단계(LLM/rule source) 도입 전까지는 `tourapi` 적재만 허용해 DB 제약 위반을 조기에 차단해야 한다.

## Decision

`CongestionRepository`는 무결성(UPSERT), 결정성(매칭), 성능(캐시 갱신 범위) 3축을 우선하는 정책으로 고정한다.

1. **UPSERT는 partial UK 2종으로 분리한다.**
   - `content_id IS NOT NULL` 행은 `(content_id, base_ymd, source)` 기준 UPSERT.
   - `content_id IS NULL` 행은 `(area_cd, signgu_cd, raw_tats_name, base_ymd, source)` 기준 UPSERT.
   - matched/unmatched를 한 트랜잭션에서 배치 처리한다 (둘 중 하나 실패 시 전체 rollback).

2. **source 입력은 현재 `tourapi`만 허용한다.**
   - repository 진입 시 `source != 'tourapi'`가 있으면 `ValueError`로 즉시 실패시킨다.
   - 이유: `llm` source는 `trace NOT NULL` 제약이 있어, 후속 PR 전에는 잘못된 적재를 명시적으로 차단해야 한다.

3. **1단계 이름 매칭은 "시군구 + 공백 정규화"로 고정한다.**
   - 비교식: `regexp_replace(title, '\s+', '', 'g') = regexp_replace(raw_name, '\s+', '', 'g')`.
   - `ORDER BY content_id`를 넣어 동률 후보에서 항상 같은 row를 선택한다 (결정성 보장).
   - 약어/이형(예: 영문 약칭)은 1단계 범위 밖으로 두고 unmatched로 남긴다.

4. **캐시 갱신은 "today row 존재 spot만" 부분 갱신한다.**
   - `today_concentration_rate`: `base_ymd = TODAY (KST)` 값으로 갱신.
   - `upcoming_concentration_avg`: `base_ymd ∈ [TODAY+1, TODAY+3]` 평균 (today 미포함).
   - `concentration_updated_at`는 갱신 시각으로 일괄 업데이트.
   - `is_active = TRUE`만 갱신 대상으로 제한한다.
   - 오늘 forecast row가 없는 spot은 이전 값을 유지한다 (의도적 stale 허용).

5. **stale 허용은 운영 가드와 함께 관리한다.**
   - full reset + 전체 UPDATE는 현 시점에서 채택하지 않는다 (핫패스 write 비용 증가).
   - stale 관측은 `concentration_updated_at`와 `SYNC_LOGS`의 `match_rate/null_ratio`로 추적한다.
   - 운영 가드: `match_rate < 0.90` 또는 `null_ratio >= SPOTS_CONGESTION_MAX_NULL_RATIO`이면 캐시 갱신 skip.

## Consequences

### Pros
- nullable key 시나리오에서도 중복 적재 없이 멱등성을 확보한다.
- 이름 공백 변형(띄어쓰기 차이)에 대한 매칭 recall이 개선된다.
- 동률 후보의 결과가 안정되어 운영 디버깅 비용이 줄어든다.
- 캐시 갱신 write 범위를 줄여 `SPOTS_CORE` 핫패스 부담을 낮춘다.

### Cons / 주의
- `regexp_replace` 비교는 일반 인덱스를 직접 활용하기 어렵다 (시군구 필터 의존).
- 오늘 row가 없는 spot은 stale 값이 남는다 (정책적으로 허용).
- 1단계 매칭은 약어/이형을 해결하지 못해 unmatched가 누적될 수 있다.

### 비채택 대안
- **full reset + 전체 UPDATE**: 최신성은 높지만 일일 write 비용과 인덱스 갱신 부담이 커서 기각.
- **exact match only**: 구현은 단순하지만 띄어쓰기 변형에서 false negative 증가로 기각.
- **초기부터 LLM/rule source 동시 허용**: trace 제약 및 운영 복잡도 증가로 단계적 도입 원칙에 맞지 않아 기각.

## 관련 문서

- `docs/operation.md` §3 `SPOT_CONGESTION_FORECAST`
- `docs/operation.md` §3 `SPOTS_CORE` 캐시 컬럼 정책
- `docs/operation.md` §3 `SYNC_LOGS` metadata 표준 필드
- `docs/adr/0001-llm-matching-strategy.md`
- `docs/adr/0003-spots-deactivation-safety-guards.md`
- `docs/adr/0004-domain-boundary-and-congestion-split.md`
- `src/nolleo_pipeline/domains/congestion/repository.py`

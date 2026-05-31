# ADR 0001 — 외부 데이터 매칭 전략: 룰 점수 + 회색지대 LLM 검증

- 상태: Partially Superseded by ADR 0006
- 일자: 2026-04-27
- 적용 범위: GOOD_PRICE_SHOPS ↔ SPOTS_CORE 매칭, SPOT_CONGESTION_FORECAST.raw_tats_name → SPOTS_CORE 매칭, 향후 추가될 외부 소스 매칭

> 현재 스키마에서는 `GOOD_PRICE_SHOPS`와 `SPOTS_CORE`를 사용하지 않는다.
> 음식 장소 매칭은 `food_place_spot_matches` ↔ `spots` 기준으로 해석한다.
> 혼잡도 매칭은 현재 마이그레이션 범위 밖이다.

## Context

외부 API 간 명칭 표기가 불일치한다 (예: `해운대 해수욕장` ↔ `해운대해수욕장` ↔ `해운대비치`).
DB는 바이트 단위 비교라 공백·약어·이형 차이를 자동 흡수하지 못한다. 한편 모든 후보를
LLM에 던지면 비용·지연이 폭증한다. operation.md §3 GOOD_PRICE_MATCH_QUEUE가 이미 룰 기반
점수 + 임계값 3단(자동/큐잉/미진입) 흐름을 잡아두었다.

## Decision

2단계 + Batch 방식으로 운영한다.

1. **1단계 — 룰 점수 후보 추출** (실시간/Batch 공용)
   - 필터: 같은 시군구 + 카테고리 호환 + 좌표 거리 ≤ 200m
   - 가중치: 전화 0.5 / 이름 0.3 (Jaro-Winkler) / 주소 0.15 / 거리 0.05
   - `pg_trgm`은 후보 좁히기용으로만 쓰고, 점수 산정엔 Jaro-Winkler 사용
   - 임계값 분기:
     - `≥ 0.85` → 자동 approved + SPOTS_CORE 연결 (LLM 미경유)
     - `0.65 ~ 0.85` → 회색지대 → 2단계로 전달
     - `< 0.65` → MATCH_QUEUE 미진입, 별도 처리(separate)

2. **2단계 — LLM 검증** (Batch 전용)
   - 입력: 룰 점수 회색지대 후보들 + overview/주소/카테고리
   - 출력: 최종 content_id + LLM confidence
   - LLM confidence도 임계값 두 개:
     - `≥ 0.85` + 룰 검증 통과 → 자동 적용
     - 그 외 → MATCH_QUEUE에 pending으로 큐잉, 관리자 검수
   - 추적 필드 필수: `model_name`, `model_version`, `prompt_version`,
     `source_text_hash` (BHR_QUEUE와 동일 패턴)

3. **Batch 운영**
   - 실시간 매칭 X — sync 시 1단계만 시도하고 회색지대는 unmatched로 적재
   - 일 1회 cron이 unmatched 모아 LLM 호출
   - 모델/프롬프트 변경 시 정답 셋 100쌍 회귀 → 일치율 ≥ 95%일 때만 결과 반영

## Consequences

### Pros
- LLM 호출은 회색지대로 한정 → 비용·지연 통제 가능
- 룰만으로 처리 가능한 케이스(전화번호 일치 등)는 즉시 매칭 → 핫패스 영향 X
- 추적 필드 필수화로 모델 갱신·디버깅 가능

### Cons / 주의
- LLM 비결정성 → 회귀 정답 셋 운영 비용 발생 (관리자 시간)
- 회색지대 정의가 늘어나면 LLM 비용도 비선형 증가 — 임계값(`0.65 / 0.85`)은 데이터 누적 후 재튜닝
- 1단계 후보 필터(시군구·200m·카테고리)가 너무 좁으면 false negative ↑ → recall 모니터 필요

### 비채택 대안
- **전체 LLM**: 비용/지연 폭증, 회귀 검증도 광범위해짐 → 기각
- **룰만**: 이름 변형이 큰 케이스(약어, 띄어쓰기) recall 낮음 → 보완 필요
- **실시간 LLM**: 외부 API sync 핫패스 지연 + 동시성 폭증 → Batch로 분리

## 관련 문서

- `docs/operation.md` §3 GOOD_PRICE_MATCH_QUEUE 임계값 정책
- `docs/operation.md` §3 BUSINESS_HOURS_REVIEW_QUEUE 회귀 검증 패턴
- `docs/operation.md` §3 SPOT_CONGESTION_FORECAST.content_id nullable 정책

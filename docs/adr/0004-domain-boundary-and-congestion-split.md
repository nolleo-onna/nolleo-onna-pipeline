# ADR 0004 — 도메인 분리 기준과 SPOTS 혼잡도(congestion) 분리 원칙

- 상태: Proposed
- 일자: 2026-05-07
- 적용 범위: `src/nolleo_pipeline/domains/*`, SPOTS 혼잡도 파이프라인/운영 정책

## Context

현재 코드베이스는 도메인별 패키지(`domains/spots`, `events`, `travel_courses`, `good_price` 등)로 구성되어 있으나,
"언제 별도 도메인(또는 서브도메인)으로 분리하는가"에 대한 명시 규칙이 문서에 약하다.

- 혼잡도(`SPOT_CONGESTION_FORECAST`)는 스팟과 연관되지만, 데이터 성격(예측 시계열), 무결성 규칙(partial UK 2종), 운영 잡(sync/cache refresh/purge), 보존 정책(30일+7일)이 SPOTS 본체와 다르다.
- 분리 기준이 문서화되지 않으면, 신규 파이프라인 추가 시 폴더 구조/책임 경계가 사람마다 달라져 리뷰 비용이 증가한다.
- 장애 격리와 운영 가시성(SYNC_LOGS 표준 필드)을 유지하려면 "분리해야 하는 조건"을 공통 규약으로 고정할 필요가 있다.

## Decision

도메인 분리 기준을 "데이터 책임 + 운영 책임" 관점으로 명문화하고, 혼잡도는 해당 기준을 충족하는 독립 서브도메인으로 유지한다.

1. **도메인 분리 트리거(충족 시 독립 패키지 권장)**
   - 외부 원천/API가 본체와 다르고, 호출 단위/페이지네이션/에러 모델이 별도일 것
   - 독립 스케줄(별도 cron), 별도 실패 처리, 별도 SYNC_LOGS metadata가 필요할 것
   - 본체와 다른 무결성 규칙(예: nullable key, partial UK, 별도 upsert 키 정책)을 가질 것
   - 보존/정리 정책(purge cutoff)이 본체와 다를 것
   - 핫패스 성능 보호를 위해 비동기 배치 + 캐시 반영 경계가 필요할 것

2. **패키지 책임 계약(도메인 공통 구조)**
   - `client.py`: 외부 API 프로토콜 책임(재시도/에러 파싱 포함)
   - `parser.py` + `models.py`: 원본 → 정규화 레코드 변환 책임
   - `repository.py`: DB 무결성/UPSERT/캐시 SQL/정리 SQL 책임
   - `pipeline.py`: 잡 오케스트레이션, 가드 평가, metadata 기록 책임
   - 도메인 간 직접 결합 대신 `SPOTS_CORE` 같은 공용 SoT 테이블로 조인한다.

3. **혼잡도(congestion) 분리 판정**
   - `SPOT_CONGESTION_FORECAST`는 스팟의 "속성 컬럼"이 아니라 독립 예측 데이터셋으로 취급한다.
   - 이유:
     - TourAPI 엔드포인트/응답 형식이 다름
     - `content_id` nullable + partial UK 2종 등 별도 무결성 규칙 존재
     - `sync → cache_refresh → purge` 3단 잡과 가드(ADR 0003 재사용) 필요
     - `SPOTS_CORE.today_concentration_rate` 등은 결과 캐시이며, 원천 SoT는 forecast 테이블임
   - 따라서 `domains/congestion` 패키지로 분리하고, `spots`는 캐시 소비자 역할에 집중한다.

4. **분리하지 않는 기준 (반례)**
   - 동일 API/동일 주기/동일 무결성 규칙을 공유하고, 운영 잡 분리가 불필요한 경우
   - 본체 파이프라인 내부의 단순 파생 계산(추가 테이블/잡/보존정책 없음)인 경우

## Consequences

### Pros
- 신규 도메인 추가 시 폴더 구조와 책임 경계가 일관되어 리뷰/온보딩 비용이 감소한다.
- 장애 격리(부분 실패 흡수)와 운영 가시성(SYNC_LOGS metadata 표준화)이 강화된다.
- 핫패스 테이블(`SPOTS_CORE`)과 배치성 예측 데이터의 책임이 분리되어 성능/유지보수성이 좋아진다.

### Cons / 주의
- 패키지 수가 늘어나 초기 진입자가 "왜 분리했는지"를 문서로 학습해야 한다.
- 도메인 간 협업(예: 캐시 반영)에서 인터페이스 계약이 느슨하면 중복 로직이 생길 수 있다.
- 분리 기준을 과도하게 적용하면 작은 기능도 불필요하게 쪼개질 수 있다.

### 비채택 대안
- **전부 `domains/spots` 내부 하위 모듈로 유지**: 단기 단순하지만, 혼잡도 전용 무결성/잡/보존 규칙이 섞여 파일 비대화와 장애 전파 위험 증가.
- **테이블 기준으로만 분리(운영 책임 미고려)**: 스케줄/가드/metadata 규약이 코드 구조에 반영되지 않아 운영 디버깅 난이도 상승.
- **기능 단위 임의 분리(명시 기준 없음)**: 사람마다 구조가 달라져 리뷰 합의 비용 증가.

## 관련 문서

- `docs/erd.md` "도메인 구성 한눈에", "핵심 설계 패턴"
- `docs/operation.md` §3 "도메인별 상세 운영 정책"
- `docs/operation.md` §3 `SPOT_CONGESTION_FORECAST` 정책
- `docs/operation.md` §3 `SYNC_LOGS` metadata 표준 필드
- `docs/adr/0003-spots-deactivation-safety-guards.md`
- [Issue #11 — SPOTS 혼잡도 파이프라인](https://github.com/nolleo-onna/nolleo-onna-pipeline/issues/11)
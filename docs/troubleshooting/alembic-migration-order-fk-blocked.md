# Alembic 마이그레이션 순서로 인한 외부 FK 적용 차단

## 문제

- 로컬 DB에서 SPOTS 스키마를 올리기 위해 `alembic upgrade head` 실행 중 중단.
- 외부 FK 단계에서 `UndefinedTable: relation "ldong_codes" does not exist` 발생.
- 트리거 자체는 master 테이블 비의존인데 체인 순서 때문에 함께 막힘.

## 원인

- 기존 체인: `... -> 0003(indexes) -> 0004(external_fks) -> 0005(updated_at_triggers)`.
- `0004 external_fks`는 `ldong_codes`, `lcls_systm_codes`, `tags` 선행 생성이 필요.
- master 테이블이 없어서 `0004`가 실패했고, 뒤 `0005`도 실행되지 못함.

## 해결

- 체인 재배치: `... -> 0003(indexes) -> 0004(updated_at_triggers) -> 0005(external_fks)`.
- 트리거를 먼저 적용 가능하도록 분리하고, 외부 FK는 master 준비 후 마지막에 적용.
- 결과: 트리거 리비전까지 정상 적용, 외부 FK는 의도적으로 대기.

## 확인

- `SELECT version_num FROM alembic_version;` 결과가 `0004_spots_updated_at_triggers`.
- 트리거 4개 존재 확인: `spots_core`, `spot_details`, `spot_embeddings`, `spots_raw_snapshots`.
- FK 제약(`fk_spots_core_*`, `fk_spot_tags_tag`, `fk_spot_congestion_signgu`) 미존재 확인(정상).
- 외부 FK 적용 전 선행 점검 테이블: `public.ldong_codes`, `public.lcls_systm_codes`, `public.tags`.


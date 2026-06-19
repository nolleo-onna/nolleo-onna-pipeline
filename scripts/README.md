# scripts/

배치 파이프라인을 **수동 1회 실행**하거나, DB를 부트스트랩/리셋할 때 쓰는 운영용 스크립트 모음입니다.
정기 스케줄링은 APScheduler(앱 내부)가 담당하고, 이 디렉토리는 최초 적재·백필·smoke test·재처리 등 손으로 돌려야 하는 작업을 모아둡니다.

## 실행 방법

모든 Python 스크립트는 레포 루트에서 `uv run`으로 실행합니다.

```bash
uv run python scripts/<경로>.py [옵션]
```

SQL 스크립트는 `psql`로 직접 실행합니다.

```bash
psql "$DATABASE_URL" -f scripts/db/<파일>.sql
```

> 전제: `.env` 설정(`DATABASE_URL`, TourAPI/Kakao/OpenAI 키 등), `uv sync` 완료, `alembic upgrade head` 적용.

## 디렉토리 구조

```text
scripts/
├── db/                 # DB 부트스트랩 / 리셋 (SQL)
├── courses/            # 여행코스(ContentTypeId=25) sync
├── food/               # 음식·착한가격업소 적재 및 후처리 파이프라인
├── backfill_*.py       # 일회성 백필
├── probe_*.py          # API 응답 검증 (DB 적재 X)
└── run_*.py            # 도메인별 수동 sync
```

## db/ — DB 부트스트랩·리셋 (SQL)

| 파일 | 설명 |
| --- | --- |
| `00_provision_extensions.sql` | PostGIS / pgvector / pg_trgm 확장 설치. 자가 운영 PG는 superuser로 1회, 매니지드 PG는 콘솔에서. dev는 docker-compose initdb 마운트로 자동. |
| `01_drop_all_tables.sql` | `public` 스키마 전체 테이블 drop. **dev 재부트스트랩 전용**(확장은 유지). |

```bash
psql "$DATABASE_URL" -f scripts/db/00_provision_extensions.sql
psql "$DATABASE_URL" -f scripts/db/01_drop_all_tables.sql   # ⚠ 모든 테이블 삭제
```

## spots — 관광지 sync (루트)

| 스크립트 | 설명 |
| --- | --- |
| `run_spots_sync.py` | 부산(법정동 시도 26) 관광지 전량 sync — ContentType 12/14/28/39. |
| `run_spots_sync_28.py` | 부산 레포츠(ContentTypeId=28)만 sync. |
| `backfill_lcls_systm_codes.py` | TourAPI KorService2 `lclsSystmCode2` → `lcls_systm_codes` 분류코드 백필. 신규 contentType 적재 누락 보강용. (문서: `docs/troubleshooting/lcls-systm-master-backfill.md`) |

```bash
uv run python scripts/run_spots_sync.py
uv run python scripts/run_spots_sync_28.py
uv run python scripts/backfill_lcls_systm_codes.py
```

## congestion — 혼잡도 (루트)

| 스크립트 | 설명 |
| --- | --- |
| `probe_congestion_api.py` | 시군구 1개만 호출해 응답 형식·API 키 검증 (DB 적재 X). 실 적재 전 안전장치. API 호출 1건. |
| `run_congestion_sync.py` | 부산 혼잡도 sync + SPOTS 캐시 갱신 + 7일 이전 cleanup 1회 실행(smoke test). ⚠ 개발계정 일 1,000건 한도. |

```bash
uv run python scripts/probe_congestion_api.py      # 먼저 응답 검증
uv run python scripts/run_congestion_sync.py
```

## courses/ — 여행코스 sync

| 스크립트 | 설명 |
| --- | --- |
| `run_travel_courses_sync.py` | 부산(시도 26) 여행코스(ContentTypeId=25) 전량 sync. |

```bash
uv run python scripts/courses/run_travel_courses_sync.py
```

## food/ — 음식·착한가격업소 파이프라인

`fd_food_*` 테이블 적재 후 병합·지오코딩·매칭·가격요약까지 단계별로 후처리합니다.
대부분 `--dry-run`, `--limit` 옵션을 지원하므로 먼저 `--dry-run`으로 영향 범위를 확인한 뒤 실행하세요.
(상세 가이드: `docs/troubleshooting/good-price-food-pipeline.md`)

### 1) 원천 적재 (Source sync)

| 스크립트 | 설명 | 주요 옵션 |
| --- | --- | --- |
| `run_good_price_api_sync.py` | 부산 착한가격업소 API → `good_price_store` 적재. | `--max-pages`, `--num-of-rows` |
| `run_good_price_menu_sync.py` | 부산 착한가격업소 메뉴 API → `good_price_menu` 적재. | `--max-pages`, `--num-of-rows` |
| `run_good_price_odcloud_sync.py` | odcloud 착한가격업소 데이터셋 API 적재. | `--endpoint-url`(필수), `--source-name`(필수), `--max-pages`, `--per-page` |
| `run_busan_food_sync.py` | 부산맛집정보 API → `fd_food_*` 적재. | `--max-pages`, `--num-of-rows` |
| `import_good_price_csv.py` | 착한가격업소 CSV/파일 → `fd_food_*` 적재. | `path`(필수 인자) |

### 2) 후처리 (Enrich / Match)

| 스크립트 | 설명 | 주요 옵션 |
| --- | --- | --- |
| `run_food_place_store_enrich.py` | `good_price_store`의 주소·좌표·연락처를 `good_price_menu`에 병합. | `--dry-run`, `--limit` |
| `run_food_place_geocode.py` | `fd_food_places` 주소 → Kakao Local API 좌표 지오코딩. | `--dry-run`, `--limit` |
| `run_food_place_address_inference.py` | 주소 없는 장소를 Kakao 키워드 + LLM 추론으로 주소·좌표 보강. | `--dry-run`, `--limit`, `--skip-llm` |
| `run_food_spot_match.py` | `fd_food_places` ↔ `spots` 룰 매칭 → `fd_food_place_spot_matches` 적재. | `--dry-run`, `--limit`, `--rematch-pending` |
| `refresh_spot_price_summary.py` | `fd_food_*` 현재 메뉴 가격 → `sp_spot_price_summary` 갱신. | `--dry-run`, `--prune-missing` |

### 권장 실행 순서

```bash
# 1) 원천 적재
uv run python scripts/food/run_good_price_menu_sync.py
uv run python scripts/food/run_good_price_api_sync.py          # good_price_store

# 2) store → menu 주소/좌표 병합
uv run python scripts/food/run_food_place_store_enrich.py --dry-run
uv run python scripts/food/run_food_place_store_enrich.py

# 3) 주소 → 좌표 지오코딩
uv run python scripts/food/run_food_place_geocode.py --dry-run
uv run python scripts/food/run_food_place_geocode.py

# 4) 주소 없는 장소 추론 보강 (LLM 비용 주의 — 먼저 --skip-llm으로 점검)
uv run python scripts/food/run_food_place_address_inference.py --skip-llm --dry-run --limit 20
uv run python scripts/food/run_food_place_address_inference.py --skip-llm

# 5) spots 매칭
uv run python scripts/food/run_food_spot_match.py --dry-run
uv run python scripts/food/run_food_spot_match.py

# 6) 가격 요약 갱신
uv run python scripts/food/refresh_spot_price_summary.py --dry-run
uv run python scripts/food/refresh_spot_price_summary.py
```

## 결과 확인

대부분의 sync 스크립트는 `sync_logs` 테이블에 실행 결과를 남깁니다.

```bash
psql "$DATABASE_URL" -c "
  SELECT id, job_name, status, records_fetched, records_upserted,
         records_failed, duration_seconds
    FROM sync_logs
   ORDER BY id DESC LIMIT 10;
"
```
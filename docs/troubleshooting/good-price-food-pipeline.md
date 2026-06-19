# 착한가격(fd_food_*) 파이프라인 트러블슈팅 기록

관광공사 TourAPI `sp_spots`(39)와 행정 착한가격(`fd_food_*`) 연동 과정에서 겪은 문제·원인·해결·재실행 명령을 시간순으로 정리한다.

## 배경 / 목표

- `fd_food_place_menus` 가격을 `sp_spots`에 연결해 `sp_spot_price_summary` 캐시를 채우려 함.
- 착한가격은 원천 API가 여러 개(`good_price_menu`, `good_price_store`, `good_price_file` 등)이고, **원천마다 별도 `fd_food_places` row**로 적재됨 (ADR 0006).
- 메뉴 API는 주소·좌표가 없고, 목록 API·CSV는 주소가 있는 경우가 많음.

## 권장 실행 순서 (현재 기준)

```bash
# 0. 원천 sync (필요 시)
uv run python scripts/food/run_good_price_menu_sync.py
uv run python scripts/food/run_good_price_api_sync.py   # good_price_store

# 1. store → menu 메타 병합 (이름 일치)
uv run python scripts/food/run_food_place_store_enrich.py --dry-run
uv run python scripts/food/run_food_place_store_enrich.py

# 2. 주소 → 좌표 (주소 있는 row)
uv run python scripts/food/run_food_place_geocode.py --dry-run
uv run python scripts/food/run_food_place_geocode.py

# 3. 주소·좌표 없는 row — Kakao 키워드 (+ 선택 LLM)
uv run python scripts/food/run_food_place_address_inference.py --skip-llm --dry-run --limit 20
uv run python scripts/food/run_food_place_address_inference.py --skip-llm

# 4. (선택) TourAPI 스팟 ↔ 착한가격 룰 매칭
uv run python scripts/food/run_food_spot_match.py --dry-run
uv run python scripts/food/run_food_spot_match.py

# 5. (선택, matched 있을 때만 의미 있음) 스팟 가격 요약
uv run python scripts/food/refresh_spot_price_summary.py
```

---

## 1. `sp_spot_price_summary`가 0건

### 증상

```bash
uv run python scripts/food/refresh_spot_price_summary.py
# aggregated=0, upserted=0
```

### 원인

- 요약 SQL은 `fd_food_place_spot_matches.match_status = 'matched'` 인 row만 집계함.
- 매칭 테이블이 비어 있거나 `matched`가 없으면 항상 0건.

### 해결

- 선행: 좌표 보강 → `run_food_spot_match.py`로 `matched` 생성.
- (후속 결론) TourAPI 스팟과 착한가격 overlap이 작아 **가격 SoT는 `fd_food_place_menus` 직접 사용**이 현실적.

### 확인

```sql
SELECT match_status, COUNT(*) FROM fd_food_place_spot_matches GROUP BY match_status;
SELECT COUNT(*) FROM sp_spot_price_summary;
```

---

## 2. `run_food_spot_match` — `matched=0`, `no_candidate` 다수

### 증상

```bash
uv run python scripts/food/run_food_spot_match.py --dry-run
# places_scanned=100, matched=0, separate=18, no_candidate=82  (초기, 좌표 100건만)
# places_scanned=801, matched=0, separate=10, no_candidate=791  (좌표 확대 후)
```

### 원인 (복합)

| 원인 | 설명 |
|------|------|
| 좌표 부족 | 초기에는 CSV 100건만 `geog` 보유 |
| `sp_spots`(39) 부족 | AWS DB 음식점 **435건**, 부산 전역 착한가격(1600+)과 겹침 적음 |
| 거리 필터 | 기본 **200m** `ST_DWithin` — 후보 없으면 `no_candidate` |
| 점수 임계값 | 후보 있어도 이름·전화 불일치 시 `separate` (최대 점수 ~0.50, pending 기준 0.65) |
| row 분리 | 매칭이 `good_price_store` row에 쌓이면 **메뉴 가격과 무관** (`good_price_menu`에 메뉴 SoT) |

### 시도 / 판단

- 반경 500m 확대 → recall만 올고 정확도 우선 정책과 충돌 → **200m 복원**.
- 이름·주소·전화 정규화, 모호 후보 downgrade 가드 추가 (`matcher.py`).
- **spot 재적재 없이** 진행 시 `no_candidate` 878건(메뉴·geog·200m 내 스팟 0)은 구조적 한계.

### 확인

```sql
-- 메뉴 row, 200m 내 음식점 스팟 수
SELECT COUNT(*) FROM fd_food_places fp
  JOIN fd_food_place_sources src ON src.food_place_id = fp.id AND src.source = 'good_price_menu'
 WHERE fp.is_active AND fp.geog IS NOT NULL
   AND EXISTS (
        SELECT 1 FROM sp_spots s
         WHERE s.is_active AND s.content_type_id = '39' AND s.geog IS NOT NULL
           AND ST_DWithin(fp.geog, s.geog, 200)
   );
```

---

## 3. 메뉴 1615건 주소 0 — `good_price_store`도 0건

### 증상

```sql
-- 메뉴: 주소 없음 1615
-- store: 주소 있음 0
```

### 원인

1. **멀티 소스 설계**: `good_price_menu` row와 `good_price_store` row는 **별도** `fd_food_places`. 메뉴 쿼리만 보면 주소 0이 정상.
2. **목록 API sync 실패**: `good_price_store_sync`가 `records_upserted=0`, `records_failed=993`.
   - DB CHECK 제약 `food_place_sources_source_check`에 **`good_price_store` 값 미포함** (코드는 `good_price_store`, DB는 `good_price_shop`만 허용).

### 해결

- AWS RDS에 제약 수정 (레포 `0010_add_good_price_store_source.py`와 동일 내용, 당시 `alembic upgrade`는 `0009` FK 이슈로 막혀 **SQL 직접 실행**).

```sql
ALTER TABLE public.fd_food_place_sources
    DROP CONSTRAINT IF EXISTS food_place_sources_source_check;
ALTER TABLE public.fd_food_place_sources
    DROP CONSTRAINT IF EXISTS fd_food_place_sources_source_check;
ALTER TABLE public.fd_food_place_sources
    ADD CONSTRAINT fd_food_place_sources_source_check
    CHECK (source IN (
        'good_price_shop', 'good_price_store', 'good_price_menu', 'good_price_file',
        'redtable', 'busan_food', 'model_restaurant', 'admin_manual'
    ));
```

- 이후 목록 sync 재실행:

```bash
uv run python scripts/food/run_good_price_api_sync.py
# 중단돼도 upsert (source, external_id) 기준 안전 — 같은 명령 재실행
```

### 확인

```sql
SELECT source, COUNT(*) FROM fd_food_place_sources GROUP BY source;
-- good_price_store 약 993, good_price_menu 1615, good_price_file 100
```

---

## 4. store → menu 주소·좌표 병합

### 증상

- 메뉴 row는 가격 SoT인데 주소·`geog` 없음.
- store row에는 주소 있으나 메뉴와 **다른 `food_place_id`**.

### 해결

- 스크립트 추가: `scripts/food/run_food_place_store_enrich.py`
- 업소명 일치 시 menu row에 store의 `address`, `tel`, `source_region`, `map_x`, `map_y` 보강 (빈 필드만).

```bash
uv run python scripts/food/run_food_place_store_enrich.py --dry-run
# menu_scanned=1615, store_matches=932, enriched=875, address_filled=119, coords_filled=113, tel_filled=859

uv run python scripts/food/run_food_place_store_enrich.py
```

### 한계

- `no_store_match=683`: 목록 API에 없는 메뉴 업소는 병합 불가 → 주소 추론(3단계) 필요.

---

## 5. `run_food_place_geocode` — 40건 전부 실패

### 증상

```bash
uv run python scripts/food/run_food_place_geocode.py
# places_scanned=40, geocoded=0, failed=40
```

### 원인

- 목록 API `adres` 필드가 **도로명+지번을 붙여서** 저장됨.

```
부산 기장군 정관읍 모전2길 1-7부산 기장군 정관읍 모전리 744-6, 1층
                              ↑ 구분 없이 연결
```

- Kakao 주소 API가 파싱 실패 → `unresolved_addresses` (API 예외 아님).

### 해결

- `normalize_address_for_geocode()` 개선 (`geocoding/parser.py`):
  - 두 번째 `부산` 기준 분리 → 도로명 구간 우선
  - `(46762)` 우편번호 제거
  - `부산` → `부산광역시` 보정

```bash
uv run python scripts/food/run_food_place_geocode.py --dry-run --limit 10
# geocoded=8, failed=2

uv run python scripts/food/run_food_place_geocode.py
# geocoded=26, failed=14
```

---

## 6. `run_food_place_address_inference` — 346건 전부 실패

### 증상

```bash
uv run python scripts/food/run_food_place_address_inference.py --skip-llm --dry-run --limit 20
# resolved=19/20 (초기 쉬운 샘플)

uv run python scripts/food/run_food_place_address_inference.py --skip-llm
# places_scanned=346, resolved=0, failed=346
```

### 원인

- 대상 346건 = store 병합·geocode 후에도 **주소·좌표 둘 다 없는** `good_price_menu` 잔여.
- Kakao 키워드 검색 결과 없음 또는 업소명 유사도 < 0.75 (`errors` 없음 → API 장애 아님).
- 예: `옥이가 머리하는 곳` — `tel`, `source_region` 없음, Kakao docs=0.

### 해결 / 판단

- `--skip-llm`만으로는 한계. `OPENAI_API_KEY` 설정 후 LLM fallback 검토.
- **전체 1615 커버는 비현실** — 메뉴 row `geog` 1267건으로 서비스 가능.

### 스크립트

`scripts/food/run_food_place_address_inference.py` (Kakao 키워드 → 선택 LLM → 주소·좌표 저장)

---

## 7. `run_spots_sync` — `relation "spots" does not exist`

### 증상

```bash
uv run python scripts/run_spots_sync.py
# psycopg.errors.UndefinedTable: relation "spots" does not exist
```

### 원인

- AWS RDS 테이블: `sp_spots`, `sp_spot_details`, `sp_spot_images`, `sp_spots_raw_snapshots`
- `spots/repository.py`는 마이그레이션 0003 기준 비접두사 `spots` 사용.

### 해결

- `src/nolleo_pipeline/domains/spots/repository.py`에 `sp_` prefix 상수 반영.
  - `SPOTS_TABLE = "sp_spots"` 등

```bash
# 검증 (1페이지)
uv run python -c "
import asyncio
from nolleo_pipeline.common.db import close_pool
from nolleo_pipeline.domains.spots.pipeline import run_tourapi_spots_sync
async def main():
    await run_tourapi_spots_sync(l_dong_regn_cd='26', max_pages=1, num_of_rows=10)
    await close_pool()
asyncio.run(main())
"

# 전체 (선택, 시간 소요)
uv run python scripts/run_spots_sync.py
```

### 참고

- 공모전 맥락에서 **spot 전량 재적재 없이** 진행하기로 한 경우, 음식점 435건 기준으로 `no_candidate`는 크게 줄지 않음.

---

## 8. 테이블 prefix / 제약 혼동

### 자주 헷갈리는 점

| 질문 | 답 |
|------|-----|
| `good_price_store` 테이블이 따로 있나? | **아니오.** `fd_food_place_sources.source` 값임 |
| 메뉴 1615 주소 0이 버그? | **아니오.** 메뉴 API 스펙 + 별도 row 구조 |
| `geog` 다 들어갔나? | **부분.** menu 1267/1615, 전체 row 2348/2708 |
| `0010` alembic 적용됐나? | AWS `alembic_version`은 0008, 제약은 SQL로 직접 반영 |

### 확인 쿼리

```sql
SELECT src.source, COUNT(*) AS cnt,
       COUNT(*) FILTER (WHERE fp.address IS NOT NULL AND BTRIM(fp.address) <> '') AS with_addr,
       COUNT(*) FILTER (WHERE fp.geog IS NOT NULL) AS with_geog
  FROM fd_food_place_sources src
  JOIN fd_food_places fp ON fp.id = src.food_place_id
 WHERE fp.is_active = TRUE
 GROUP BY src.source;
```

---

## 최종 상태 요약 (2026-06-06 경)

| 항목 | 수치 |
|------|------|
| `good_price_menu` | 1615 (geog ~1267) |
| `good_price_store` | ~993 (주소 대부분, 메뉴 없음) |
| `good_price_file` | 100 |
| `sp_spots` content_type 39 | ~435 |
| `fd_food_place_spot_matches` matched | **0** |
| `sp_spot_price_summary` | **0** |

## 아키텍처 결론 (공모전 / TourAPI 활용)

- **TourAPI**: 코스·관광 스팟·지도 레이어 (관광공사 API 활용).
- **착한가격**: `fd_food_places` + `fd_food_place_menus` + `geog`로 **독립 가성비 레이어**.
- TourAPI 음식점과 **1:1 전량 매칭은 기대하지 않음**. 겹치는 구간만 LLM 2단계(ADR 0001)로 소수 연동 가능.
- 코스 식사 슬롯 → **거리 기준 근처 착한가격 추천**은 spot `matched` 없이 구현 가능.

## 관련 파일

| 구분 | 경로 |
|------|------|
| 메뉴↔store 병합 | `scripts/food/run_food_place_store_enrich.py` |
| 주소 지오코딩 | `scripts/food/run_food_place_geocode.py` |
| 주소·좌표 추론 | `scripts/food/run_food_place_address_inference.py` |
| 스팟 룰 매칭 | `scripts/food/run_food_spot_match.py` |
| 가격 요약 캐시 | `scripts/food/refresh_spot_price_summary.py` |
| 목록 API sync | `scripts/food/run_good_price_api_sync.py` |
| TourAPI 스팟 sync | `scripts/run_spots_sync.py` |
| 주소 정규화 | `src/nolleo_pipeline/domains/geocoding/parser.py` |
| 매칭 점수 | `src/nolleo_pipeline/domains/good_price/matcher.py` |
| sp_ 테이블 I/O | `src/nolleo_pipeline/domains/spots/repository.py` |
| source CHECK | `alembic/versions/0010_add_good_price_store_source.py` |

## 관련 ADR / 문서

- `docs/adr/0001-llm-matching-strategy.md` — 룰 점수 + 회색지대 LLM
- `docs/adr/0006-food-price-common-domain.md` — `fd_food_*` 멀티 소스
- `docs/operation.md` — `fd_food_place_spot_matches` 임계값 정책

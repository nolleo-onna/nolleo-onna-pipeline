# AWS RDS 재부트스트랩 가이드

AWS dev DB를 비우거나 새 RDS 인스턴스를 만든 뒤, 현재 Alembic 리셋 체인
(`0001` → `0008`)을 기준으로 다시 초기화하는 절차입니다.

## 1. 환경변수 갱신

`.env.aws` 또는 `.env`에 새 인스턴스 정보를 반영합니다.

```bash
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=
TOUR_API_KEY=
OPENAI_API_KEY=
```

로컬 셸에 로드합니다.

```bash
set -a
source .env.aws
set +a
```

## 2. DB 접속 확인

```bash
psql "host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER sslmode=require"
```

접속이 안 되면 보안그룹 인바운드(5432), 사용자/비밀번호, DB 이름을 먼저 점검합니다.

## 3. 기존 테이블 정리

dev DB를 완전히 새로 올릴 때만 실행합니다. PostGIS/pgvector 시스템 테이블과 extension은
삭제 대상이 아닙니다.

```bash
psql "host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER sslmode=require" \
  -f scripts/db/01_drop_all_tables.sql
```

## 4. Alembic 마이그레이션 적용

현재 리포의 단일 head는 `0008`입니다.

```bash
uv run alembic heads
uv run alembic upgrade head
```

`0001`에서 `postgis`, `pg_trgm`, `vector` extension을 `CREATE EXTENSION IF NOT EXISTS`로
보장합니다. RDS 권한 문제로 extension 생성이 실패하면 DB owner 권한을 먼저 확인합니다.

## 5. 결과 확인

```sql
SELECT * FROM alembic_version;
\dt public.*
```

현재 MVP 기준 최소 테이블:

- `users`
- `spots`, `spot_details`, `spots_raw_snapshots`, `spot_images`
- `travel_courses`, `travel_course_raw_snapshots`, `course_items`
- `generated_courses`, `generated_course_items`, `course_decisions`
- `sync_logs`
- `food_places`, `food_place_sources`, `food_place_menus`
- `food_price_observations`, `food_place_spot_matches`, `spot_price_summary`
- `ldong_codes`

## 6. 스모크 테스트

초기에는 소량으로 시작합니다.

```bash
uv run python -u scripts/spot/run_spots_sync.py
```

필요하면 스크립트에서 `max_pages=1`, `num_of_rows=5`로 줄여 먼저 확인합니다.

## 7. 적재 로그 검증

```sql
SELECT id, job_name, status, api_calls_used, records_fetched, records_upserted,
       records_failed, metadata
FROM sync_logs
ORDER BY id DESC
LIMIT 10;
```

`status='success'`와 처리 건수가 확인되면 재부트스트랩이 완료된 상태입니다.

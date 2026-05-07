# AWS RDS 재생성 후 초기화 가이드

AWS RDS 인스턴스를 삭제/재생성했을 때, 놀러온나 파이프라인을 처음부터 다시 연결하고 적재를 재개하는 절차입니다.

## 1) 환경변수 갱신

`/.env.aws`(또는 `/.env`)에 새 인스턴스 정보를 반영합니다.

- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `TOUR_API_KEY`
- `OPENAI_API_KEY`
- `DAILY_API_CALL_LIMIT` (권장: `900`, 일 1000 제한 버퍼)

로컬 셸에 로드:

```bash
set -a
source .env.aws
set +a
```

## 2) DB 접속 확인

```bash
psql "host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER sslmode=require"
```

접속이 안 되면 보안그룹 인바운드(5432), 사용자/비밀번호, DB 이름을 먼저 점검합니다.

## 3) 확장(extension) 설치

`psql` 접속 후 실행:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\dx
```

`postgis`, `vector`, `pg_trgm`가 보이면 정상입니다.

## 4) Alembic 마이그레이션 적용

프로젝트 루트에서:

```bash
./.venv/bin/alembic heads
```

현재 리포 구조상 head가 2개일 수 있습니다. 우선 SPOTS 체인(+sync_logs)만 올립니다.

```bash
./.venv/bin/alembic upgrade 0005_create_sync_logs
```

`0099_spots_external_fks`는 외부(master) 테이블 준비 후 적용합니다.

## 5) 마이그레이션 결과 확인

`psql`에서:

```sql
SELECT * FROM alembic_version;
\dt
```

최소 아래 테이블이 보여야 합니다.

- `spots_core`
- `spot_details`
- `spot_embeddings`
- `spots_raw_snapshots`
- `spot_images`
- `spot_tags`
- `spot_congestion_forecast`
- `sync_logs`

## 6) 스모크 테스트 실행

초기에는 소량으로 시작합니다.

- `scripts/run_spots_sync.py`를 `max_pages=1`, `num_of_rows=5`로 실행
- 정상 확인 후 `max_pages=None`, `num_of_rows=100`으로 전환

실행:

```bash
python -u scripts/run_spots_sync.py
```

## 7) 적재 로그 검증

```sql
SELECT id, status, api_calls_used, records_fetched, records_upserted, records_failed
FROM sync_logs
WHERE job_name='tourapi_spots_sync'
ORDER BY id DESC
LIMIT 3;
```

`status='success'`와 처리 건수가 확인되면 재연결/재부트스트랩이 완료된 상태입니다.


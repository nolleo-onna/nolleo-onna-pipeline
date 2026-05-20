# `lcls_systm_codes` 마스터 — 레포츠(28) FK 실패 시

## 증상

- `run_spots_sync_28.py` 등으로 `contentTypeId=28` 적재 시 `records_failed`가 목록 건수와 같음.
- `sync_logs.metadata.errors`에 `fk_spots_core_lcls` — `Key (lcls_systm_1, lcls_systm_2, lcls_systm_3)=(LS, …)` 가 `lcls_systm_codes`에 없다는 메시지.

## DDL 때 다 채워져야 했나?

**아니요.** 설계는 다음과 같습니다.

| 단계 | 내용 |
|------|------|
| `0007_create_lcls_systm_codes` | **빈 테이블**만 생성. 주석: 시드는 TourAPI 코드조회로 채움. |
| `0009_seed_master_codes_busan` | `spots_core`에 **이미 들어 있는** `(lcls_systm_1,2,3)` DISTINCT만 `lcls_systm_codes`에 `pending_sync`로 백필. |
| `0099_spots_external_fks` | `spots_core` → `lcls_systm_codes` 복합 FK 부착. |

즉 마이그레이션은 **“기존 스팟에 쓰이던 분류”**만 자동으로 넣습니다.  
**28번(레포츠)은 예전에 `spots_core`에 없었으면** `LS` 계열 코드가 마스터에 없는 채로 남습니다. 이건 마이그레이션 버그가 아니라 **백필 소스가 `spots_core`뿐**이라 생기는 공백입니다.

## 해결 (권장): TourAPI `lclsSystmCode2`로 채우기

KorService2 분류체계 코드 조회 API로 `LS`(레포츠/레저 계열) 등 필요한 트리를 받아 `lcls_systm_codes`에 넣습니다.

프로젝트 루트에서 (`.env`에 `TOUR_API_KEY`, DB 연결 정보):

```bash
uv run python -u scripts/backfill_lcls_systm_codes.py --dry-run
uv run python -u scripts/backfill_lcls_systm_codes.py --lcls-systm1 LS
```

- 기본값 `--lcls-systm1 LS` — 부산 28 스팟이 쓰는 대분류가 `LS`인 경우.
- 다른 대분류도 비어 있으면 같은 스크립트로 `--lcls-systm1 VE` 등 반복 가능.
- 응답 필드가 예상과 다르면 `--dry-run`으로 한 페이지만 받아 구조를 확인한 뒤 스크립트의 파서를 조정합니다.

적재 후:

```bash
uv run python -u scripts/run_spots_sync_28.py
```

## `psql` 명령이 안 잡힐 때

`brew install libpq`가 이미 되어 있어도 zsh PATH에 `psql`이 없으면
`command not found: psql`이 발생한다.

```bash
echo 'export PATH="/opt/homebrew/opt/libpq/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

직접 접속 예시:

```bash
set -a && source .env && set +a
PGPASSWORD="$DB_PASSWORD" psql \
  "host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER sslmode=require"
```

## 해결 (임시): 수동 INSERT

에러에 나온 `(code1, code2, code3)` 튜플을 그대로 넣을 수 있습니다. 이름은 당분간 `pending_sync`로 두고, 나중에 공식 명칭으로 UPDATE해도 됩니다.

```sql
INSERT INTO lcls_systm_codes (code1, code2, code3, name) VALUES
  ('LS', 'LS01', 'LS011900', 'pending_sync')
ON CONFLICT (code1, code2, code3) DO NOTHING;
```

66건 전부 커버하려면 누락 조합을 계속 추가하거나, 위 **TourAPI 백필 스크립트**를 쓰는 편이 낫습니다.

## 확인 쿼리

```sql
SELECT code1, COUNT(*) FROM lcls_systm_codes GROUP BY 1 ORDER BY 1;
SELECT COUNT(*) FROM spots_core WHERE content_type_id = '28';
```

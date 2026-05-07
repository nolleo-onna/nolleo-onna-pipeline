# TourAPI 혼잡도 sync `signgu_cd` 형식 mismatch로 0건 수집

## 문제

- `tourapi_congestion_sync`에서 부산 16개 시군구를 모두 순회(`signgus_completed=16`)했는데 `records_fetched=0`으로 종료됨.
- probe 호출(`signguCd=26110`)은 정상 응답이었지만, 본 sync 경로는 빈 `items`만 반환됨.

## 원인

- `ldong_codes.signgu_cd`는 내부 표준 3자리(`110`, `140`, ...)인데, TourAPI 혼잡도 endpoint는 `signguCd`를 5자리 결합 코드(`26110`)로 기대함.
- sync가 LDONG 코드(3자리)를 그대로 API에 전달해 시군구별 호출이 모두 빈 응답이 됨.

## 해결

- 내부 표준(3자리)은 유지하고, **API 호출 시점에서만** `area_cd + signgu_cd`로 5자리 결합 코드를 만들어 전달.
  - `src/nolleo_pipeline/domains/congestion/pipeline.py`
    - `_sync_one_signgu()`에서 `api_signgu_cd = f"{area_cd}{signgu_cd}"` 생성
    - `client.list_by_signgu(signgu_cd=api_signgu_cd)`로 호출
- TourAPI 응답 파싱 시에는 다시 3자리 표준으로 정규화해 저장/매칭 정합 유지.
  - `src/nolleo_pipeline/domains/congestion/parser.py`
    - `signguCd`가 `areaCd` prefix로 시작하면 prefix 제거
    - `CongestionForecastRecord.signgu_cd`에 3자리 코드 저장

## 확인

- LDONG 코드가 3자리임을 확인:

```sql
SELECT regn_cd, signgu_cd, name
  FROM ldong_codes
 WHERE regn_cd = '26'
 ORDER BY signgu_cd
 LIMIT 5;
```

예시 결과:

- `26 | 110 | 중구`
- `26 | 140 | 서구`
- `26 | 170 | 동구`

- 문제 시점 sync 로그 확인:

```sql
SELECT id, job_name, api_calls_used, records_fetched
  FROM sync_logs
 WHERE id = 22;
```

예시 결과:

- `api_calls_used = 16` (호출은 수행됨)
- `records_fetched = 0` (응답 데이터 없음)

- 패치 후 정상 수집 로그 확인:
  - `records_fetched = 8010`
  - `records_upserted = 8010`
  - `signgus_completed = 16`
  - `bootstrap_complete = true`


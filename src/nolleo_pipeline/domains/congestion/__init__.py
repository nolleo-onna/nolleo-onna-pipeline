"""Congestion 도메인.

[이 패키지가 왜 있냐]
- TourAPI tatsCnctrRateService를 우리 SPOT_CONGESTION_FORECAST에 적재.
- SPOTS_CORE 캐시 컬럼(today/upcoming concentration) 갱신.
- 7일 이전 예측 row cleanup.

[흐름]
client (호출) → parser (정규화) → repository (UPSERT/매칭/캐시/cleanup)
                                            ↑
                                       pipeline이 묶음
"""
"""seed master codes — Busan 16 ldong + defensive backfill from existing data

operation.md §3 코드/날씨 마스터 #LDONG_CODES.

목적:
- 0099_spots_external_fks 가 spots_core 에 외부 FK를 부착하기 직전,
  참조 대상 마스터 코드(ldong_codes / lcls_systm_codes)가 비어 있으면
  기존 spots_core 행에 대한 FK 검증이 실패한다.
- 그래서 0099 직전에 시드 + 방어적 백필을 강제한다.

동작:
1) 부산 16개 시군구를 ldong_codes에 INSERT (ON CONFLICT DO NOTHING — 멱등).
   regn_cd='26' (TourAPI lDongRegnCd), signgu_cd 는 3자리 (lDongSignguCd 원본).
2) 운영 중 RDS에 이미 적재된 spots_core / spot_congestion_forecast 의
   DISTINCT (regn, signgu) / (area, signgu) 조합을 ldong_codes 에 보충 INSERT.
   이름은 'pending_sync' 플레이스홀더 — TourAPI 코드조회 sync 잡이 향후 UPDATE.
3) 동일하게 spots_core.lcls_systm_1/2/3 의 DISTINCT 조합을 lcls_systm_codes 에
   보충 INSERT (이름 'pending_sync').

이 시드는 멱등하므로 fresh DB / 운영 DB 모두 안전하게 적용된다.

Revision ID: 0009_seed_master_codes_busan
Revises: 0008_create_tags
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0009_seed_master_codes_busan"
down_revision = "0008_create_tags"
branch_labels = None
depends_on = None


# 부산 16개 시군구 (TourAPI 4.0 lDongRegnCd='26' / lDongSignguCd 3자리)
BUSAN_DISTRICTS: tuple[tuple[str, str, str], ...] = (
    ("26", "110", "중구"),
    ("26", "140", "서구"),
    ("26", "170", "동구"),
    ("26", "200", "영도구"),
    ("26", "230", "부산진구"),
    ("26", "260", "동래구"),
    ("26", "290", "남구"),
    ("26", "320", "북구"),
    ("26", "350", "해운대구"),
    ("26", "380", "사하구"),
    ("26", "410", "금정구"),
    ("26", "440", "강서구"),
    ("26", "470", "연제구"),
    ("26", "500", "수영구"),
    ("26", "530", "사상구"),
    ("26", "710", "기장군"),
)


def upgrade() -> None:
    # 1) 부산 16개 시군구 정식 시드
    values_sql = ",\n        ".join(
        f"('{regn}', '{signgu}', '{name}')"
        for regn, signgu, name in BUSAN_DISTRICTS
    )
    op.execute(f"""
    INSERT INTO ldong_codes (regn_cd, signgu_cd, name) VALUES
        {values_sql}
    ON CONFLICT (regn_cd, signgu_cd) DO NOTHING;
    """)

    # 2) 운영 데이터 방어적 백필 — spots_core 에 이미 있는 코드를 ldong_codes 로 끌어올림.
    #    이름은 'pending_sync' 플레이스홀더, 후속 sync 잡(코드조회 endpoint)이 UPDATE.
    op.execute("""
    INSERT INTO ldong_codes (regn_cd, signgu_cd, name)
    SELECT DISTINCT l_dong_regn_cd, l_dong_signgu_cd, 'pending_sync'
    FROM spots_core
    WHERE l_dong_regn_cd IS NOT NULL
      AND l_dong_signgu_cd IS NOT NULL
    ON CONFLICT (regn_cd, signgu_cd) DO NOTHING;
    """)

    # 3) 혼잡도 예측 테이블 방어적 백필 — area_cd / signgu_cd 도 ldong_codes 참조 대상.
    op.execute("""
    INSERT INTO ldong_codes (regn_cd, signgu_cd, name)
    SELECT DISTINCT area_cd, signgu_cd, 'pending_sync'
    FROM spot_congestion_forecast
    WHERE area_cd IS NOT NULL
      AND signgu_cd IS NOT NULL
    ON CONFLICT (regn_cd, signgu_cd) DO NOTHING;
    """)

    # 4) lcls_systm_codes 방어적 백필 — spots_core 에 적재된 분류 코드.
    op.execute("""
    INSERT INTO lcls_systm_codes (code1, code2, code3, name)
    SELECT DISTINCT lcls_systm_1, lcls_systm_2, lcls_systm_3, 'pending_sync'
    FROM spots_core
    WHERE lcls_systm_1 IS NOT NULL
      AND lcls_systm_2 IS NOT NULL
      AND lcls_systm_3 IS NOT NULL
    ON CONFLICT (code1, code2, code3) DO NOTHING;
    """)


def downgrade() -> None:
    # 멱등 시드 — downgrade 시 명시적으로 부산 16개만 제거.
    # spots_core 에서 끌어올린 'pending_sync' 행은 그대로 두면 다음 upgrade 시
    # 다시 ON CONFLICT DO NOTHING으로 흡수되므로 무해.
    busan_pairs = ",\n        ".join(
        f"('{regn}', '{signgu}')" for regn, signgu, _ in BUSAN_DISTRICTS
    )
    op.execute(f"""
    DELETE FROM ldong_codes
    WHERE (regn_cd, signgu_cd) IN ({busan_pairs});
    """)

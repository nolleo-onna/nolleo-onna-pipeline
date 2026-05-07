"""create good_price_locale_codes (착한가격 동 코드 마스터)

operation.md §3 코드/날씨 마스터 #GOOD_PRICE_LOCALE_CODES / ERD §GOOD_PRICE_LOCALE_CODES.

- 착한가격 API locale 코드 마스터 (GOOD_PRICE_SHOPS.locale_code SoT).
- LDONG_CODES.signgu_cd 매핑 브리지 테이블.
- 초기 시드: 부산 행정동 코드 전체 등록 (운영 시드 스크립트로).
- 무결성: 미등록 locale_code 유입 시 GOOD_PRICE_SHOPS 적재 실패 + SYNC_LOGS 경고.

Revision ID: 0102_create_gp_locale_codes
Revises: 0101_create_weather_cache
Create Date: 2026-05-07

NOTE: revision id는 alembic_version.version_num VARCHAR(32) 제약 때문에 짧게 유지.
"""
from __future__ import annotations

from alembic import op

revision = "0102_create_gp_locale_codes"
down_revision = "0101_create_weather_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # signgu_cd / signgu_name: 상위 시군구 캐시 (역정규화).
    # ldong_codes 복합 PK라 단독 signgu_cd 참조 FK는 불가. regn_cd 동반 필요.
    # 부산 운영 한정이라 regn_cd='26' 강제 가능 — 지금은 컬럼 추가 없이
    # signgu_name만 캐시하고 정합성은 시드/적재 잡에서 검증.
    op.execute("""
    CREATE TABLE good_price_locale_codes (
        locale_cd     VARCHAR(20)  PRIMARY KEY,
        locale_name   VARCHAR(100) NOT NULL,
        signgu_cd     VARCHAR(5)   NOT NULL,
        signgu_name   VARCHAR(100) NOT NULL
    );
    """)

    # 시군구 그룹 조회용
    op.execute("""
    CREATE INDEX idx_good_price_locale_signgu
        ON good_price_locale_codes (signgu_cd);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_good_price_locale_signgu;")
    op.execute("DROP TABLE IF EXISTS good_price_locale_codes;")

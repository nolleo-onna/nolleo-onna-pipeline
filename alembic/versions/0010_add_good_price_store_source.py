"""fd_food_place_sources 의 source CHECK 에 good_price_store 원천 추가.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# 신규 빌드(0007 인라인 CHECK)는 fd_food_place_sources_source_check 로,
# Flyway 이전 구버전은 food_place_sources_source_check 로 명명되어 있을 수 있어 모두 정리.
_DROP = """
ALTER TABLE public.fd_food_place_sources
    DROP CONSTRAINT IF EXISTS fd_food_place_sources_source_check;
ALTER TABLE public.fd_food_place_sources
    DROP CONSTRAINT IF EXISTS food_place_sources_source_check;
"""


def upgrade() -> None:
    op.execute(_DROP)
    op.execute("""
    ALTER TABLE public.fd_food_place_sources
        ADD CONSTRAINT fd_food_place_sources_source_check
        CHECK (source IN (
            'good_price_shop',
            'good_price_store',
            'good_price_menu',
            'good_price_file',
            'redtable',
            'busan_food',
            'model_restaurant',
            'admin_manual'
        ));
    """)


def downgrade() -> None:
    op.execute(_DROP)
    op.execute("""
    ALTER TABLE public.fd_food_place_sources
        ADD CONSTRAINT fd_food_place_sources_source_check
        CHECK (source IN (
            'good_price_shop',
            'good_price_menu',
            'good_price_file',
            'redtable',
            'busan_food',
            'model_restaurant',
            'admin_manual'
        ));
    """)

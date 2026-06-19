"""fd_food_place_sources에 good_price_store 원천 추가."""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.fd_food_place_sources
            DROP CONSTRAINT IF EXISTS food_place_sources_source_check;
        """
    )
    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.fd_food_place_sources
            DROP CONSTRAINT IF EXISTS fd_food_place_sources_source_check;
        """
    )
    op.execute(
        """
        ALTER TABLE public.fd_food_place_sources
            ADD CONSTRAINT food_place_sources_source_check
            CHECK (source IN (
                'good_price_shop',
                'good_price_menu',
                'good_price_file',
                'redtable',
                'busan_food',
                'model_restaurant',
                'admin_manual'
            ));
        """
    )

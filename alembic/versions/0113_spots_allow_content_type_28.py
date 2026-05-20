"""allow content_type_id 28 (레포츠) on spots_core

TourAPI areaBasedList2 contentTypeId 28 — SPOT_CONTENT_TYPE_IDS 확장에 맞춤.
0001_create_spots_tables CHECK는 이미 적용된 환경이므로 여기서만 갱신.

Revision ID: 0113_spots_allow_content_type_28
Revises: 0112_attach_user_fks
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op

revision = "0113_spots_allow_content_type_28"
down_revision = "0112_attach_user_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE spots_core
        DROP CONSTRAINT IF EXISTS spots_core_content_type_id_check;
    """)
    op.execute("""
    ALTER TABLE spots_core
        ADD CONSTRAINT spots_core_content_type_id_check
        CHECK (content_type_id IN ('12', '14', '28', '39'));
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE spots_core
        DROP CONSTRAINT IF EXISTS spots_core_content_type_id_check;
    """)
    op.execute("""
    ALTER TABLE spots_core
        ADD CONSTRAINT spots_core_content_type_id_check
        CHECK (content_type_id IN ('12', '14', '39'));
    """)

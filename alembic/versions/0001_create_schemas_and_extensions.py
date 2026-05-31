"""create base schemas and required extensions

Revision ID: 0001
Revises:
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MVP 기준: 서비스 테이블은 public, 임베딩용은 vectors 스키마(추후 사용).
    op.execute("CREATE SCHEMA IF NOT EXISTS public;")
    op.execute("CREATE SCHEMA IF NOT EXISTS vectors;")

    # 현재 스키마에서 사용하는 확장.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 공통 updated_at 트리거 함수.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.set_updated_at()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        NEW.updated_at := NOW();
        RETURN NEW;
    END
    $$;
    """)


def downgrade() -> None:
    # 확장은 다른 객체 의존성이 생기기 쉬워 제거하지 않는다.
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at();")
    op.execute("DROP SCHEMA IF EXISTS vectors;")

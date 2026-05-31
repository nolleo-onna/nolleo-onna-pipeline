"""create ldong codes

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.ldong_codes (
        regn_cd     VARCHAR(2)   NOT NULL,
        signgu_cd   VARCHAR(5)   NOT NULL,
        name        VARCHAR(100) NOT NULL,
        PRIMARY KEY (regn_cd, signgu_cd)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.ldong_codes IS 'TourAPI 법정동 시군구 코드 마스터';
    COMMENT ON COLUMN public.ldong_codes.regn_cd IS '법정동 시도 코드';
    COMMENT ON COLUMN public.ldong_codes.signgu_cd IS '법정동 시군구 코드';
    COMMENT ON COLUMN public.ldong_codes.name IS '시군구명';
    """)

    op.execute("""
    INSERT INTO public.ldong_codes (regn_cd, signgu_cd, name) VALUES
        ('26', '110', '중구'),
        ('26', '140', '서구'),
        ('26', '170', '동구'),
        ('26', '200', '영도구'),
        ('26', '230', '부산진구'),
        ('26', '260', '동래구'),
        ('26', '290', '남구'),
        ('26', '320', '북구'),
        ('26', '350', '해운대구'),
        ('26', '380', '사하구'),
        ('26', '410', '금정구'),
        ('26', '440', '강서구'),
        ('26', '470', '연제구'),
        ('26', '500', '수영구'),
        ('26', '530', '사상구'),
        ('26', '710', '기장군');
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.ldong_codes;")

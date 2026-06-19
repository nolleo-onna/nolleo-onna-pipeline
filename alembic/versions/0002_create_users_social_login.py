"""create minimal user table for social login

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.mb_user_info (
        id                  BIGSERIAL    PRIMARY KEY,
        external_id         VARCHAR(120) NOT NULL,
        provider            VARCHAR(20)  NOT NULL
            CHECK (provider IN ('kakao', 'naver', 'google')),
        email               VARCHAR(255),
        nickname            VARCHAR(80),
        profile_image_url   TEXT,
        role                VARCHAR(20)  NOT NULL DEFAULT 'user'
            CHECK (role IN ('user', 'admin')),
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        created_by          VARCHAR(50),
        updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_by          VARCHAR(50),
        last_active_at      TIMESTAMPTZ,
        deleted_at          TIMESTAMPTZ,
        deleted_by          VARCHAR(50),
        CONSTRAINT uk_mb_user_info_provider_external UNIQUE (provider, external_id)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.mb_user_info IS '소셜 로그인 기반 사용자 마스터';
    COMMENT ON COLUMN public.mb_user_info.id IS '내부 사용자 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.mb_user_info.external_id IS '소셜 제공자 외부 사용자 식별자';
    COMMENT ON COLUMN public.mb_user_info.provider IS '소셜 제공자(kakao/naver/google)';
    COMMENT ON COLUMN public.mb_user_info.email IS '사용자 이메일(제공되지 않을 수 있음)';
    COMMENT ON COLUMN public.mb_user_info.nickname IS '표시용 닉네임';
    COMMENT ON COLUMN public.mb_user_info.profile_image_url IS '프로필 이미지 URL';
    COMMENT ON COLUMN public.mb_user_info.role IS '서비스 권한(user/admin)';
    COMMENT ON COLUMN public.mb_user_info.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.mb_user_info.created_by IS '생성 주체(CreateAudit)';
    COMMENT ON COLUMN public.mb_user_info.updated_at IS '수정 시각(UpdateAudit)';
    COMMENT ON COLUMN public.mb_user_info.updated_by IS '수정 주체(UpdateAudit)';
    COMMENT ON COLUMN public.mb_user_info.last_active_at IS '최근 활동 시각';
    COMMENT ON COLUMN public.mb_user_info.deleted_at IS '소프트 삭제 시각(DeleteAudit)';
    COMMENT ON COLUMN public.mb_user_info.deleted_by IS '소프트 삭제 주체(DeleteAudit)';
    """)

    op.execute("""
    CREATE INDEX idx_mb_user_info_active_last_seen
        ON public.mb_user_info (last_active_at DESC)
        WHERE deleted_at IS NULL;
    """)

    op.execute("""
    CREATE INDEX idx_mb_user_info_email
        ON public.mb_user_info (email)
        WHERE email IS NOT NULL;
    """)

    op.execute("""
    CREATE TRIGGER trg_mb_user_info_updated_at
        BEFORE UPDATE ON public.mb_user_info
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_mb_user_info_updated_at ON public.mb_user_info;")
    op.execute("DROP INDEX IF EXISTS public.idx_mb_user_info_email;")
    op.execute("DROP INDEX IF EXISTS public.idx_mb_user_info_active_last_seen;")
    op.execute("DROP TABLE IF EXISTS public.mb_user_info;")

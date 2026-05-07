"""create users + user_embeddings (Spring 사용자 도메인)

operation.md §3 사용자 도메인 / ERD §USERS, USER_EMBEDDINGS.

설계 포인트:
- 인증: 카카오/네이버/구글 OAuth (`(provider, external_id)` 복합 UK).
- 익명 사용자 미운영 (소셜 로그인 진입장벽 낮음).
- role: 'user' / 'admin'.
- soft delete: deleted_at (30일 유예 후 hard delete cron).
- last_active_at: 5분 throttle 갱신.
- 탈퇴 처리:
  - 본인 데이터 (BOOKMARKS, VISIT_HISTORY, USER_EMBEDDINGS): 카스케이드 삭제
  - 공개 데이터 (USER_REVIEWS): user_id SET NULL 익명화 보존

USER_EMBEDDINGS:
- 콜드 스타트: 활동 5건 미만 → row 미생성 (조건은 애플리케이션 레벨).
- 갱신: 일 1회 새벽 배치 (sync_logs.user_embedding_recompute job).

Revision ID: 0107_create_users_tables
Revises: 0106_create_business_hours_review_queue
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0107_create_users_tables"
down_revision = "0106_create_bhr_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) USERS
    op.execute("""
    CREATE TABLE users (
        id                  BIGSERIAL    PRIMARY KEY,
        external_id         VARCHAR(100) NOT NULL,
        provider            VARCHAR(20)  NOT NULL
            CHECK (provider IN ('kakao','naver','google')),
        email               VARCHAR(200),
        nickname            VARCHAR(50)  NOT NULL,
        profile_image_url   TEXT,
        role                VARCHAR(20)  NOT NULL DEFAULT 'user'
            CHECK (role IN ('user','admin')),
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        last_active_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ,
        CONSTRAINT uk_users_provider_external UNIQUE (provider, external_id)
    );
    """)

    # 활성 유저 검색
    op.execute("""
    CREATE INDEX idx_users_active
        ON users (last_active_at DESC)
        WHERE deleted_at IS NULL;
    """)

    # 이메일 검색 (중복 가입 방지 lookup)
    op.execute("""
    CREATE INDEX idx_users_email
        ON users (email)
        WHERE email IS NOT NULL AND deleted_at IS NULL;
    """)

    # 2) USER_EMBEDDINGS (1:1)
    op.execute("""
    CREATE TABLE user_embeddings (
        user_id          BIGINT       PRIMARY KEY
            REFERENCES users(id) ON DELETE CASCADE,
        taste_embedding  vector(1536) NOT NULL,
        model_name       VARCHAR(80)  NOT NULL,
        model_version    VARCHAR(40)  NOT NULL,
        activity_count   INTEGER      NOT NULL DEFAULT 0
            CHECK (activity_count >= 0),
        embedded_at      TIMESTAMPTZ  NOT NULL,
        updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    """)

    # 의미 추천: "내 취향과 닮은 다른 유저 찾기" — 향후 옵션. 일단 HNSW 부착.
    op.execute("""
    CREATE INDEX idx_user_embeddings_hnsw
        ON user_embeddings USING hnsw (taste_embedding vector_cosine_ops);
    """)

    # 3) updated_at 트리거
    op.execute("""
    CREATE TRIGGER trg_user_embeddings_updated_at
        BEFORE UPDATE ON user_embeddings
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_user_embeddings_updated_at ON user_embeddings;")
    op.execute("DROP INDEX IF EXISTS idx_user_embeddings_hnsw;")
    op.execute("DROP TABLE IF EXISTS user_embeddings;")
    op.execute("DROP INDEX IF EXISTS idx_users_email;")
    op.execute("DROP INDEX IF EXISTS idx_users_active;")
    op.execute("DROP TABLE IF EXISTS users;")

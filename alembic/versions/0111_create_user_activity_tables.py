"""create user_reviews + visit_history + notifications

operation.md §3 사용자 도메인 / ERD §USER_REVIEWS, VISIT_HISTORY, NOTIFICATIONS.

USER_REVIEWS:
- (user_id, spot_content_id) UK with deleted_at IS NULL — 1유저 1스팟 1리뷰.
- content 500자 / rating 1~5 CHECK.
- soft delete 30일 후 hard delete cron.
- user_id nullable + ON DELETE SET NULL: 탈퇴 사용자 리뷰 익명화 보존.
- 리뷰 변경 시 SPOTS_CORE.avg_rating/review_count 동기 갱신 (애플리케이션 레벨).
- Rate Limit 1유저 시간당 5리뷰는 애플리케이션.

VISIT_HISTORY:
- (user_id, spot_content_id) UK + visit_count 누적.
- 리뷰 작성 시 자동 upsert (애플리케이션 트리거).

NOTIFICATIONS:
- type enum: course_saved / event_upcoming / spot_closed_today / hankkut_approved.
- MVP는 인앱 전용. 보존 90일.
- 사용자당 100건 상한 (오래된 것부터 삭제) — cron.

Revision ID: 0111_create_user_activity_tables
Revises: 0110_create_bookmark_tables
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0111_create_user_activity_tables"
down_revision = "0110_create_bookmark_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) USER_REVIEWS
    op.execute("""
    CREATE TABLE user_reviews (
        id              BIGSERIAL   PRIMARY KEY,
        user_id         BIGINT
            REFERENCES users(id) ON DELETE SET NULL,
        spot_content_id VARCHAR(20) NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        content         TEXT
            CHECK (content IS NULL OR char_length(content) <= 500),
        rating          SMALLINT    NOT NULL
            CHECK (rating BETWEEN 1 AND 5),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at      TIMESTAMPTZ
    );
    """)

    # 1유저 1스팟 1리뷰 (활성만)
    op.execute("""
    CREATE UNIQUE INDEX uk_user_reviews_user_spot_active
        ON user_reviews (user_id, spot_content_id)
        WHERE deleted_at IS NULL AND user_id IS NOT NULL;
    """)

    # 스팟 상세: 최신 리뷰
    op.execute("""
    CREATE INDEX idx_user_reviews_spot_created
        ON user_reviews (spot_content_id, created_at DESC)
        WHERE deleted_at IS NULL;
    """)

    # 마이페이지: 내 리뷰
    op.execute("""
    CREATE INDEX idx_user_reviews_user_created
        ON user_reviews (user_id, created_at DESC)
        WHERE deleted_at IS NULL AND user_id IS NOT NULL;
    """)

    # 2) VISIT_HISTORY
    op.execute("""
    CREATE TABLE visit_history (
        id                  BIGSERIAL   PRIMARY KEY,
        user_id             BIGINT      NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        spot_content_id     VARCHAR(20) NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        first_visited_at    DATE        NOT NULL,
        last_visited_at     DATE        NOT NULL,
        visit_count         SMALLINT    NOT NULL DEFAULT 1
            CHECK (visit_count >= 1),
        with_companion      VARCHAR(30),
        note                TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uk_visit_history_user_spot UNIQUE (user_id, spot_content_id),
        CONSTRAINT chk_visit_history_dates
            CHECK (last_visited_at >= first_visited_at)
    );
    """)

    # 마이페이지: 방문 이력 시간순
    op.execute("""
    CREATE INDEX idx_visit_history_user_last
        ON visit_history (user_id, last_visited_at DESC);
    """)

    # 3) NOTIFICATIONS
    op.execute("""
    CREATE TABLE notifications (
        id          BIGSERIAL    PRIMARY KEY,
        user_id     BIGINT       NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        type        VARCHAR(40)  NOT NULL
            CHECK (type IN ('course_saved','event_upcoming','spot_closed_today','hankkut_approved')),
        title       VARCHAR(200) NOT NULL,
        body        TEXT,
        target_url  TEXT,
        is_read     BOOLEAN      NOT NULL DEFAULT FALSE,
        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        read_at     TIMESTAMPTZ
    );
    """)

    # 미확인 알림 뱃지 카운트
    op.execute("""
    CREATE INDEX idx_notifications_user_unread
        ON notifications (user_id, created_at DESC)
        WHERE is_read = false;
    """)

    # 90일 cron 청소
    op.execute("""
    CREATE INDEX idx_notifications_created
        ON notifications (created_at);
    """)

    # 4) updated_at 트리거
    for table in ("user_reviews", "visit_history"):
        op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    for table in ("visit_history", "user_reviews"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute("DROP INDEX IF EXISTS idx_notifications_created;")
    op.execute("DROP INDEX IF EXISTS idx_notifications_user_unread;")
    op.execute("DROP TABLE IF EXISTS notifications;")
    op.execute("DROP INDEX IF EXISTS idx_visit_history_user_last;")
    op.execute("DROP TABLE IF EXISTS visit_history;")
    op.execute("DROP INDEX IF EXISTS idx_user_reviews_user_created;")
    op.execute("DROP INDEX IF EXISTS idx_user_reviews_spot_created;")
    op.execute("DROP INDEX IF EXISTS uk_user_reviews_user_spot_active;")
    op.execute("DROP TABLE IF EXISTS user_reviews;")

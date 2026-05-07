"""create bookmark_collections + bookmarks (Spring 사용자 도메인)

operation.md §3 사용자 도메인 #BOOKMARKS, #BOOKMARK_COLLECTIONS / ERD.

설계 포인트:
- collection_type: default (저장됨) / wishlist (가보고싶음) / custom.
- 시스템 폴더(default/wishlist) 가입 시 자동 생성 — 1유저 1개 보장 (부분 UK).
- bookmark_count: 정당한 비정규화. 애플리케이션 증감 + 주 1회 cron 보정.
- 사용자 폴더 100개 상한은 애플리케이션에서.

BOOKMARKS:
- 다형성 회피: 4개 FK 컬럼 (spot/course/event/hankkut) 중 정확히 1개 NOT NULL CHECK.
- 부분 UK 4개: (user_id, target) 조합 중복 방지.
- collection_id NOT NULL: 모든 북마크는 폴더 소속 강제.
- hard delete 정책 (다시 북마크 시 새 row).
- 사용자당 1만 개 상한은 애플리케이션 레벨.

Revision ID: 0110_create_bookmark_tables
Revises: 0109_create_generated_courses_tables
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0110_create_bookmark_tables"
down_revision = "0109_create_gen_courses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) BOOKMARK_COLLECTIONS
    op.execute("""
    CREATE TABLE bookmark_collections (
        id              BIGSERIAL    PRIMARY KEY,
        user_id         BIGINT       NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        name            VARCHAR(100) NOT NULL,
        collection_type VARCHAR(20)  NOT NULL DEFAULT 'custom'
            CHECK (collection_type IN ('default','wishlist','custom')),
        bookmark_count  SMALLINT     NOT NULL DEFAULT 0
            CHECK (bookmark_count >= 0),
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    """)

    # 시스템 폴더 1유저 1개 보장 — partial UK.
    op.execute("""
    CREATE UNIQUE INDEX uk_bookmark_collections_user_default
        ON bookmark_collections (user_id)
        WHERE collection_type = 'default';
    """)
    op.execute("""
    CREATE UNIQUE INDEX uk_bookmark_collections_user_wishlist
        ON bookmark_collections (user_id)
        WHERE collection_type = 'wishlist';
    """)

    # 마이페이지: 내 폴더 목록
    op.execute("""
    CREATE INDEX idx_bookmark_collections_user
        ON bookmark_collections (user_id, created_at);
    """)

    # 2) BOOKMARKS
    #    다형성: 4개 FK 중 정확히 1개 NOT NULL.
    op.execute("""
    CREATE TABLE bookmarks (
        id                   BIGSERIAL    PRIMARY KEY,
        user_id              BIGINT       NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        spot_content_id      VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        generated_course_id  BIGINT
            REFERENCES generated_courses(id) ON DELETE CASCADE,
        event_content_id     VARCHAR(20)
            REFERENCES events_core(content_id) ON DELETE CASCADE,
        hankkut_id           BIGINT
            REFERENCES hankkut(id) ON DELETE CASCADE,
        collection_id        BIGINT       NOT NULL
            REFERENCES bookmark_collections(id) ON DELETE CASCADE,
        note                 TEXT,
        created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

        CONSTRAINT chk_bookmarks_exactly_one_target
            CHECK (
                ( (spot_content_id IS NOT NULL)::int
                + (generated_course_id IS NOT NULL)::int
                + (event_content_id IS NOT NULL)::int
                + (hankkut_id IS NOT NULL)::int
                ) = 1
            )
    );
    """)

    # 부분 UK 4종 — 동일 유저 동일 대상 중복 방지.
    op.execute("""
    CREATE UNIQUE INDEX uk_bookmarks_user_spot
        ON bookmarks (user_id, spot_content_id)
        WHERE spot_content_id IS NOT NULL;
    """)
    op.execute("""
    CREATE UNIQUE INDEX uk_bookmarks_user_course
        ON bookmarks (user_id, generated_course_id)
        WHERE generated_course_id IS NOT NULL;
    """)
    op.execute("""
    CREATE UNIQUE INDEX uk_bookmarks_user_event
        ON bookmarks (user_id, event_content_id)
        WHERE event_content_id IS NOT NULL;
    """)
    op.execute("""
    CREATE UNIQUE INDEX uk_bookmarks_user_hankkut
        ON bookmarks (user_id, hankkut_id)
        WHERE hankkut_id IS NOT NULL;
    """)

    # Q6: 사용자 북마크 목록 — 폴더별, 시간 역순.
    op.execute("""
    CREATE INDEX idx_bookmarks_collection_created
        ON bookmarks (collection_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_bookmarks_collection_created;")
    op.execute("DROP INDEX IF EXISTS uk_bookmarks_user_hankkut;")
    op.execute("DROP INDEX IF EXISTS uk_bookmarks_user_event;")
    op.execute("DROP INDEX IF EXISTS uk_bookmarks_user_course;")
    op.execute("DROP INDEX IF EXISTS uk_bookmarks_user_spot;")
    op.execute("DROP TABLE IF EXISTS bookmarks;")
    op.execute("DROP INDEX IF EXISTS idx_bookmark_collections_user;")
    op.execute("DROP INDEX IF EXISTS uk_bookmark_collections_user_wishlist;")
    op.execute("DROP INDEX IF EXISTS uk_bookmark_collections_user_default;")
    op.execute("DROP TABLE IF EXISTS bookmark_collections;")

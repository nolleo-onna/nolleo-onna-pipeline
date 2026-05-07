"""create hankkut + N:M (spots / tags / events)

operation.md §3 콘텐츠 도메인 #HANKKUT / ERD §HANKKUT_*.

설계 포인트:
- MVP는 관리자 전용 작성 (author_user_id의 role='admin' 검증은 서비스 레이어에서).
- status: pending / approved / rejected / archived.
- source: manual / auto_event.
- 자동 한끗 cron: 매일 새벽 다가올 7일 행사 → pending 한끗 자동 생성.
- 시즌 종료 자동 archive cron: valid_until < CURRENT_DATE AND status='approved' → 'archived'.
- content 3000자 제한 CHECK.
- HANKKUT_EVENTS: 대표 행사 = display_order=1 (운영 SSOT).

N:M 매핑:
- HANKKUT_SPOTS: (hankkut_id, spot_content_id) PK
- HANKKUT_TAGS: (hankkut_id, tag_id) PK
- HANKKUT_EVENTS: (hankkut_id, event_content_id) PK + display_order UK per hankkut

Revision ID: 0108_create_hankkut_tables
Revises: 0107_create_users_tables
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0108_create_hankkut_tables"
down_revision = "0107_create_users_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) HANKKUT
    op.execute("""
    CREATE TABLE hankkut (
        id                  BIGSERIAL    PRIMARY KEY,
        title               VARCHAR(200) NOT NULL,
        category            VARCHAR(20)  NOT NULL
            CHECK (category IN ('event','free','transport','tip')),
        content             TEXT         NOT NULL
            CHECK (char_length(content) <= 3000),
        cover_image_url     TEXT,
        author_user_id      BIGINT       NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
        status              VARCHAR(20)  NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','approved','rejected','archived')),
        source              VARCHAR(20)  NOT NULL DEFAULT 'manual'
            CHECK (source IN ('manual','auto_event')),
        valid_from          DATE,
        valid_until         DATE,
        published_at        TIMESTAMPTZ,
        view_count          INTEGER      NOT NULL DEFAULT 0,
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ,
        CONSTRAINT chk_hankkut_valid_range
            CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from)
    );
    """)

    # 활성/공개 한끗 카드 리스트 (홈/카테고리 화면)
    op.execute("""
    CREATE INDEX idx_hankkut_published
        ON hankkut (category, published_at DESC)
        WHERE status = 'approved' AND deleted_at IS NULL;
    """)

    # 시즌 archive cron 인덱스
    op.execute("""
    CREATE INDEX idx_hankkut_valid_until
        ON hankkut (valid_until)
        WHERE status = 'approved' AND deleted_at IS NULL;
    """)

    # 2) HANKKUT_SPOTS (N:M)
    op.execute("""
    CREATE TABLE hankkut_spots (
        hankkut_id      BIGINT       NOT NULL
            REFERENCES hankkut(id) ON DELETE CASCADE,
        spot_content_id VARCHAR(20)  NOT NULL
            REFERENCES spots_core(content_id) ON DELETE CASCADE,
        display_order   SMALLINT     NOT NULL DEFAULT 1
            CHECK (display_order >= 1),
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        PRIMARY KEY (hankkut_id, spot_content_id)
    );
    """)

    op.execute("""
    CREATE INDEX idx_hankkut_spots_spot
        ON hankkut_spots (spot_content_id);
    """)

    # 3) HANKKUT_TAGS (N:M)
    op.execute("""
    CREATE TABLE hankkut_tags (
        hankkut_id  BIGINT      NOT NULL
            REFERENCES hankkut(id) ON DELETE CASCADE,
        tag_id      SMALLINT    NOT NULL
            REFERENCES tags(tag_id) ON UPDATE CASCADE ON DELETE CASCADE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (hankkut_id, tag_id)
    );
    """)

    # 4) HANKKUT_EVENTS (N:M, 대표 행사 = display_order=1)
    op.execute("""
    CREATE TABLE hankkut_events (
        hankkut_id        BIGINT       NOT NULL
            REFERENCES hankkut(id) ON DELETE CASCADE,
        event_content_id  VARCHAR(20)  NOT NULL
            REFERENCES events_core(content_id) ON DELETE CASCADE,
        display_order     SMALLINT     NOT NULL
            CHECK (display_order >= 1),
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        PRIMARY KEY (hankkut_id, event_content_id),
        CONSTRAINT uk_hankkut_events_display_order
            UNIQUE (hankkut_id, display_order)
    );
    """)

    # 5) updated_at 트리거 (HANKKUT만)
    op.execute("""
    CREATE TRIGGER trg_hankkut_updated_at
        BEFORE UPDATE ON hankkut
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_hankkut_updated_at ON hankkut;")
    op.execute("DROP TABLE IF EXISTS hankkut_events;")
    op.execute("DROP TABLE IF EXISTS hankkut_tags;")
    op.execute("DROP INDEX IF EXISTS idx_hankkut_spots_spot;")
    op.execute("DROP TABLE IF EXISTS hankkut_spots;")
    op.execute("DROP INDEX IF EXISTS idx_hankkut_valid_until;")
    op.execute("DROP INDEX IF EXISTS idx_hankkut_published;")
    op.execute("DROP TABLE IF EXISTS hankkut;")

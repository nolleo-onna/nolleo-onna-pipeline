"""create tags (통제어휘 + 자유태그 마스터)

operation.md §3 스팟 #TAGS / §9 canonical_tag_id 운영 정책 / ERD §TAGS.

설계 포인트:
- 카테고리 10종(mood/view/companion/activity/time/season/price/vibe/theme/facility)
- canonical_tag_id 자기 참조 FK — NULL이면 자기 자신이 정규(root)
- 정규 정책 (트리거 강제):
  1) 정규 태그는 항상 root: canonical_tag_id IS NULL
  2) 동의어는 항상 root만 참조 (다단계 체인 차단)
  3) 사후 변경 차단은 별도 로직(서비스/관리자 화면)에서 처리.
     운영 §9: "잘못된 매핑 발견 시 is_active=false + 새 태그 INSERT"
- tag_type: 'controlled' (사전 정의) / 'free' (LLM 자동 신규)
- embedding: pgvector 1536 (text-embedding-3-small). HNSW 인덱스 부착.

SPOT_TAGS / HANKKUT_TAGS 가 tag_id를 FK로 참조 (0099 / 후속에서 부착).

Revision ID: 0008_create_tags
Revises: 0007_create_lcls_systm_codes
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op

revision = "0008_create_tags"
down_revision = "0007_create_lcls_systm_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 본 테이블
    op.execute("""
    CREATE TABLE tags (
        tag_id           SMALLSERIAL PRIMARY KEY,
        tag_name         VARCHAR(50)  NOT NULL UNIQUE,
        tag_type         VARCHAR(20)  NOT NULL
            CHECK (tag_type IN ('controlled','free')),
        category         VARCHAR(20)  NOT NULL
            CHECK (category IN (
                'mood','view','companion','activity','time',
                'season','price','vibe','theme','facility'
            )),
        embedding        vector(1536),
        canonical_tag_id SMALLINT
            REFERENCES tags(tag_id) ON DELETE SET NULL,
        model_name       VARCHAR(80),
        model_version    VARCHAR(40),
        usage_count      INTEGER     NOT NULL DEFAULT 0,
        is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
        embedded_at      TIMESTAMPTZ,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 2) HNSW 인덱스 (Q3 자연어 검색 — 태그 의미 매핑).
    #    embedding NULL row(임베딩 미생성)는 인덱스 대상 제외 → partial.
    op.execute("""
    CREATE INDEX idx_tags_embedding_hnsw
        ON tags USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL;
    """)

    # 3) 활성 태그 카테고리 검색 인덱스
    op.execute("""
    CREATE INDEX idx_tags_category_active
        ON tags (category)
        WHERE is_active = true;
    """)

    # 4) canonical 정책 트리거: 다단계 체인 차단
    #    INSERT/UPDATE 시 canonical_tag_id가 가리키는 태그가 root인지(자기 canonical NULL) 검사.
    op.execute("""
    CREATE OR REPLACE FUNCTION enforce_tags_canonical_root()
    RETURNS TRIGGER AS $$
    DECLARE
        parent_canonical SMALLINT;
    BEGIN
        IF NEW.canonical_tag_id IS NULL THEN
            RETURN NEW;
        END IF;
        IF NEW.canonical_tag_id = NEW.tag_id THEN
            -- 자기 자신을 가리키면 NULL과 동치. NULL로 강제.
            NEW.canonical_tag_id := NULL;
            RETURN NEW;
        END IF;
        SELECT canonical_tag_id INTO parent_canonical
        FROM tags WHERE tag_id = NEW.canonical_tag_id;
        IF parent_canonical IS NOT NULL THEN
            RAISE EXCEPTION
                'tags.canonical_tag_id must point to a root tag '
                '(canonical_tag_id IS NULL). tag_id=% points to %, '
                'which itself points to %.',
                NEW.tag_id, NEW.canonical_tag_id, parent_canonical;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER trg_tags_canonical_root
        BEFORE INSERT OR UPDATE OF canonical_tag_id ON tags
        FOR EACH ROW EXECUTE FUNCTION enforce_tags_canonical_root();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tags_canonical_root ON tags;")
    op.execute("DROP FUNCTION IF EXISTS enforce_tags_canonical_root();")
    op.execute("DROP INDEX IF EXISTS idx_tags_category_active;")
    op.execute("DROP INDEX IF EXISTS idx_tags_embedding_hnsw;")
    op.execute("DROP TABLE IF EXISTS tags;")

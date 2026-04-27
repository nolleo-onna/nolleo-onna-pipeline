"""spots performance indexes (gist / b-tree partial / GIN trgm / HNSW)

§5 출시 시점 초안. 핫패스 쿼리(Q1·Q2·Q3·Q7) 지원용.
인덱스 생성은 PG 락을 잡으므로 prod에서 큰 테이블에 적용할 땐
CONCURRENTLY 사용을 검토 (autocommit_block 필요). 현재는 빈 테이블 가정 → 일반 생성.

Revision ID: 0003_spots_indexes
Revises: 0002_spots_peripheral_tables
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op

revision = "0003_spots_indexes"
down_revision = "0002_spots_peripheral_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # spots_core ─────────────────────────────────────────
    # Q1: 지도 뷰포트 (ST_DWithin)
    op.execute("""
    CREATE INDEX idx_spots_geog_active
        ON spots_core USING gist(geog) WHERE is_active = true;
    """)

    # Q2/Q7: 시군구 + 점수 정렬
    op.execute("""
    CREATE INDEX idx_spots_signgu_pop
        ON spots_core (l_dong_signgu_cd, popularity_score DESC)
        WHERE is_active = true;
    """)
    op.execute("""
    CREATE INDEX idx_spots_signgu_trend
        ON spots_core (l_dong_signgu_cd, trend_score DESC)
        WHERE is_active = true;
    """)

    # 키워드 부분 일치 검색 (하이브리드 검색의 키워드 측)
    op.execute("""
    CREATE INDEX idx_spots_title_trgm
        ON spots_core USING gin (title gin_trgm_ops);
    """)

    # spot_embeddings ────────────────────────────────────
    # Q3: 의미 검색 (cosine). HNSW는 빌드가 무겁다 — 큰 테이블엔 CONCURRENTLY 검토.
    op.execute("""
    CREATE INDEX idx_spot_embeddings_hnsw
        ON spot_embeddings USING hnsw (embedding vector_cosine_ops);
    """)

    # spot_tags ──────────────────────────────────────────
    # "태그로 스팟 찾기" 핫패스. PK leftmost-prefix가 content_id라 tag_id 단독 lookup엔
    # PK 인덱스가 안 쓰임 → 별도 인덱스 필요.
    op.execute("""
    CREATE INDEX idx_spot_tags_tag_score
        ON spot_tags (tag_id, score DESC)
        WHERE score >= 0.8;
    """)

    # spot_congestion_forecast ───────────────────────────
    # 시군구별 일자 조회 (캐시 컬럼 갱신 cron, 관리자 화면).
    op.execute("""
    CREATE INDEX idx_spot_congestion_signgu_date
        ON spot_congestion_forecast (signgu_cd, base_ymd);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_spot_congestion_signgu_date;")
    op.execute("DROP INDEX IF EXISTS idx_spot_tags_tag_score;")
    op.execute("DROP INDEX IF EXISTS idx_spot_embeddings_hnsw;")
    op.execute("DROP INDEX IF EXISTS idx_spots_title_trgm;")
    op.execute("DROP INDEX IF EXISTS idx_spots_signgu_trend;")
    op.execute("DROP INDEX IF EXISTS idx_spots_signgu_pop;")
    op.execute("DROP INDEX IF EXISTS idx_spots_geog_active;")
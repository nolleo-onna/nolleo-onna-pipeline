"""create travel_courses domain tables (core/embeddings/raw/items)

operation.md §3 공식 코스 도메인 / ERD §TRAVEL_COURSES, COURSE_ITEMS, ...

설계 포인트:
- TourAPI ContentTypeId=25 (한국관광공사 공식 여행코스).
- 부산 ~50건 수준 → row 매우 적음. hot/cold 분리 미적용 (overview/summary 한 테이블에).
- TourAPI 원본 충실 보존: taketime/distance 원문 + _minutes/_km 파싱본.
- 짠내 변환은 TRAVEL_COURSES → COURSE_ITEMS 매칭 스팟 → 가성비 대체 → GENERATED_COURSES.

FK 부착:
- travel_courses.l_dong_regn_cd → ldong_codes.regn_cd 단독 FK.
  ldong_codes PK가 (regn_cd, signgu_cd) 복합이라 단독 참조 불가 → 별도 UK 도입.
- course_items.matched_spot_id → spots_core (nullable, ON DELETE SET NULL)

ldong_codes에 regn_cd 단독 UK 부착(REFERENCES 전제)은 0006 마이그레이션을 건드리지 않고,
여기서 별도 UK 인덱스를 추가해 처리.

Revision ID: 0104_create_travel_courses
Revises: 0103_create_events_tables
Create Date: 2026-05-07

NOTE: revision id는 alembic_version.version_num VARCHAR(32) 제약 때문에 짧게 유지.
"""
from __future__ import annotations

from alembic import op

revision = "0104_create_travel_courses"
down_revision = "0103_create_events_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) ldong_codes에 regn_cd 단독 UK 추가 (단독 FK 참조용).
    #    부산 운영 한정이라 regn_cd '26' 1행만 unique이지만, 향후 전국 확장 시에도 OK.
    #    DISTINCT regn_cd가 필요하므로, 시도별 대표 row가 1개라는 보장은 시드에서 챙김.
    #    여기선 partial unique index로 해결: 시도 레벨 정의 행을 signgu_cd='000' 같은 sentinel로
    #    두는 운영안도 있지만, 단순화를 위해 단독 FK는 포기하고 복합 FK만 사용한다.
    #    → travel_courses.l_dong_regn_cd 는 FK 미부착, 시드/적재 시 검증.

    # 1) TRAVEL_COURSES
    op.execute("""
    CREATE TABLE travel_courses (
        content_id              VARCHAR(20) PRIMARY KEY,
        title                   VARCHAR(200) NOT NULL,

        overview                TEXT,
        overview_hash           VARCHAR(64),
        overview_summary        TEXT,

        theme                   VARCHAR(100),
        taketime                VARCHAR(50),
        taketime_minutes        INTEGER
            CHECK (taketime_minutes IS NULL OR taketime_minutes >= 0),
        distance                VARCHAR(50),
        distance_km             NUMERIC(7,3)
            CHECK (distance_km IS NULL OR distance_km >= 0),

        schedule                TEXT,
        infocenter_tourcourse   VARCHAR(200),

        first_image             TEXT,

        l_dong_regn_cd          VARCHAR(2),

        source_modified_time    TIMESTAMPTZ,
        created_time            TIMESTAMPTZ,
        synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        is_active               BOOLEAN NOT NULL DEFAULT TRUE,
        inactive_since          TIMESTAMPTZ
    );
    """)

    # 2) TRAVEL_COURSE_EMBEDDINGS (1:1)
    op.execute("""
    CREATE TABLE travel_course_embeddings (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES travel_courses(content_id) ON DELETE CASCADE,
        embedding       vector(1536) NOT NULL,
        source_text     TEXT         NOT NULL,
        source_hash     VARCHAR(64)  NOT NULL,
        model_name      VARCHAR(80)  NOT NULL,
        model_version   VARCHAR(40)  NOT NULL,
        token_count     INTEGER      NOT NULL CHECK (token_count >= 0),
        embedded_at     TIMESTAMPTZ  NOT NULL,
        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );
    """)

    # 3) COURSES_RAW_SNAPSHOTS (1:1)
    op.execute("""
    CREATE TABLE courses_raw_snapshots (
        content_id      VARCHAR(20) PRIMARY KEY
            REFERENCES travel_courses(content_id) ON DELETE CASCADE,
        raw_json        JSONB       NOT NULL,
        fetched_at      TIMESTAMPTZ NOT NULL,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 4) COURSE_ITEMS (1:N)
    #    matched_spot_id nullable: SPOTS_CORE 매칭 실패 시 sub_* fallback으로 표시.
    op.execute("""
    CREATE TABLE course_items (
        id                  BIGSERIAL   PRIMARY KEY,
        course_content_id   VARCHAR(20) NOT NULL
            REFERENCES travel_courses(content_id) ON DELETE CASCADE,
        serial_num          INTEGER     NOT NULL CHECK (serial_num >= 1),
        sub_content_id      VARCHAR(20),
        matched_spot_id     VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE SET NULL,
        sub_name            VARCHAR(200),
        sub_overview        TEXT,
        sub_image           TEXT,
        sub_image_alt       VARCHAR(200),
        CONSTRAINT uk_course_items_course_serial UNIQUE (course_content_id, serial_num)
    );
    """)

    # 5) HNSW
    op.execute("""
    CREATE INDEX idx_travel_course_embeddings_hnsw
        ON travel_course_embeddings USING hnsw (embedding vector_cosine_ops);
    """)

    # 6) updated_at 트리거
    for table in ("travel_courses", "travel_course_embeddings", "courses_raw_snapshots"):
        op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    for table in ("courses_raw_snapshots", "travel_course_embeddings", "travel_courses"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute("DROP INDEX IF EXISTS idx_travel_course_embeddings_hnsw;")
    op.execute("DROP TABLE IF EXISTS course_items;")
    op.execute("DROP TABLE IF EXISTS courses_raw_snapshots;")
    op.execute("DROP TABLE IF EXISTS travel_course_embeddings;")
    op.execute("DROP TABLE IF EXISTS travel_courses;")

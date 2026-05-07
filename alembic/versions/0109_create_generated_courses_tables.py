"""create generated_courses + items + course_decisions

operation.md §3 코스 도메인 / ERD §GENERATED_COURSES, GENERATED_COURSE_ITEMS, COURSE_DECISIONS.

설계 포인트:
- 사용자 생성 코스 전용 (운영자 큐레이션은 TRAVEL_COURSES).
- user_id NOT NULL (익명 사용자 미운영).
- weight_profile: balanced / budget_focused.
- generation_method: natural / form / recommend.
- generation_mode: taste / novelty / default.
- pair_id: 같은 입력 형제 코스 2개 묶음.
- share_token UK: 공유 URL 직접 접근.
- soft delete (30일 후 hard delete).
- "공식 코스 짠내 변환": compared_with_travel_course_id 추적.

GENERATED_COURSE_ITEMS:
- (course_id, serial_num) UK.
- 코스 편집 = row 단위 INSERT/UPDATE/DELETE.

COURSE_DECISIONS:
- decision_type: exclude / replace / boost.
- severity: critical / warning / info.
- evidence JSONB 표준 스키마.

Revision ID: 0109_create_gen_courses
Revises: 0108_create_hankkut_tables
Create Date: 2026-05-07

NOTE: revision id는 alembic_version.version_num VARCHAR(32) 제약 때문에 짧게 유지.
"""
from __future__ import annotations

from alembic import op

revision = "0109_create_gen_courses"
down_revision = "0108_create_hankkut_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) GENERATED_COURSES
    op.execute("""
    CREATE TABLE generated_courses (
        id                              BIGSERIAL   PRIMARY KEY,
        user_id                         BIGINT      NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        parent_course_id                BIGINT
            REFERENCES generated_courses(id) ON DELETE SET NULL,
        pair_id                         UUID,
        weight_profile                  VARCHAR(30)
            CHECK (weight_profile IS NULL OR weight_profile IN ('balanced','budget_focused')),
        title                           VARCHAR(200) NOT NULL,
        input_signgu                    VARCHAR(50),
        input_budget                    INTEGER     CHECK (input_budget IS NULL OR input_budget >= 0),
        input_duration                  VARCHAR(30),
        input_companion                 VARCHAR(30),
        input_mood                      TEXT[],
        generation_mode                 VARCHAR(20)
            CHECK (generation_mode IS NULL OR generation_mode IN ('taste','novelty','default')),
        generation_method               VARCHAR(20)
            CHECK (generation_method IS NULL OR generation_method IN ('natural','form','recommend')),
        total_cost                      INTEGER     CHECK (total_cost IS NULL OR total_cost >= 0),
        total_minutes                   INTEGER     CHECK (total_minutes IS NULL OR total_minutes >= 0),
        total_savings                   INTEGER,
        compared_with_travel_course_id  VARCHAR(20)
            REFERENCES travel_courses(content_id) ON DELETE SET NULL,
        weather_at_gen                  JSONB,
        is_public                       BOOLEAN     NOT NULL DEFAULT FALSE,
        share_token                     VARCHAR(64) UNIQUE,
        view_count                      INTEGER     NOT NULL DEFAULT 0,
        created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at                      TIMESTAMPTZ
    );
    """)

    # 마이페이지: 내 코스 목록
    op.execute("""
    CREATE INDEX idx_generated_courses_user_created
        ON generated_courses (user_id, created_at DESC)
        WHERE deleted_at IS NULL;
    """)

    # 형제 코스 lookup (pair_id)
    op.execute("""
    CREATE INDEX idx_generated_courses_pair
        ON generated_courses (pair_id)
        WHERE pair_id IS NOT NULL;
    """)

    # 2) GENERATED_COURSE_ITEMS
    op.execute("""
    CREATE TABLE generated_course_items (
        id                          BIGSERIAL   PRIMARY KEY,
        course_id                   BIGINT      NOT NULL
            REFERENCES generated_courses(id) ON DELETE CASCADE,
        serial_num                  SMALLINT    NOT NULL CHECK (serial_num >= 1),
        spot_content_id             VARCHAR(20) NOT NULL
            REFERENCES spots_core(content_id) ON DELETE RESTRICT,
        arrival_time                TIME,
        duration_minutes            SMALLINT    CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
        expected_cost               INTEGER     CHECK (expected_cost IS NULL OR expected_cost >= 0),
        travel_minutes_from_prev    SMALLINT    CHECK (travel_minutes_from_prev IS NULL OR travel_minutes_from_prev >= 0),
        notes                       TEXT,
        CONSTRAINT uk_generated_course_items_serial UNIQUE (course_id, serial_num)
    );
    """)

    # 3) COURSE_DECISIONS
    op.execute("""
    CREATE TABLE course_decisions (
        id                  BIGSERIAL   PRIMARY KEY,
        course_id           BIGINT      NOT NULL
            REFERENCES generated_courses(id) ON DELETE CASCADE,
        decision_type       VARCHAR(20) NOT NULL
            CHECK (decision_type IN ('exclude','replace','boost')),
        severity            VARCHAR(20) NOT NULL
            CHECK (severity IN ('critical','warning','info')),
        spot_content_id     VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE SET NULL,
        replacement_spot_id VARCHAR(20)
            REFERENCES spots_core(content_id) ON DELETE SET NULL,
        reason              TEXT,
        user_message        TEXT,
        evidence            JSONB,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # 4) updated_at 트리거 (generated_courses만)
    op.execute("""
    CREATE TRIGGER trg_generated_courses_updated_at
        BEFORE UPDATE ON generated_courses
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_generated_courses_updated_at ON generated_courses;")
    op.execute("DROP TABLE IF EXISTS course_decisions;")
    op.execute("DROP TABLE IF EXISTS generated_course_items;")
    op.execute("DROP INDEX IF EXISTS idx_generated_courses_pair;")
    op.execute("DROP INDEX IF EXISTS idx_generated_courses_user_created;")
    op.execute("DROP TABLE IF EXISTS generated_courses;")

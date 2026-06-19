"""create generated courses tables for MVP

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE public.cs_generated_courses (
        id                              BIGSERIAL    PRIMARY KEY,
        user_id                         BIGINT       NOT NULL
            REFERENCES public.mb_user_info(id) ON DELETE CASCADE,
        parent_course_id                BIGINT
            REFERENCES public.cs_generated_courses(id) ON DELETE SET NULL,
        pair_id                         UUID,
        weight_profile                  VARCHAR(30)
            CHECK (weight_profile IS NULL OR weight_profile IN ('balanced', 'budget_focused')),
        title                           VARCHAR(200) NOT NULL,
        input_signgu                    VARCHAR(50),
        input_budget                    INTEGER
            CHECK (input_budget IS NULL OR input_budget >= 0),
        input_duration                  VARCHAR(30),
        input_companion                 VARCHAR(30),
        input_mood                      TEXT[],
        generation_mode                 VARCHAR(20)
            CHECK (generation_mode IS NULL OR generation_mode IN ('taste', 'novelty', 'default')),
        generation_method               VARCHAR(20)
            CHECK (generation_method IS NULL OR generation_method IN ('natural', 'form', 'recommend')),
        total_cost                      INTEGER
            CHECK (total_cost IS NULL OR total_cost >= 0),
        total_minutes                   INTEGER
            CHECK (total_minutes IS NULL OR total_minutes >= 0),
        total_savings                   INTEGER,
        compared_with_travel_course_id  VARCHAR(20)
            REFERENCES public.tv_travel_courses(content_id) ON DELETE SET NULL,
        weather_at_gen                  JSONB,
        is_public                       BOOLEAN      NOT NULL DEFAULT FALSE,
        share_token                     VARCHAR(64),
        view_count                      INTEGER      NOT NULL DEFAULT 0
            CHECK (view_count >= 0),
        created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        created_by                      VARCHAR(50),
        updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_by                      VARCHAR(50),
        deleted_at                      TIMESTAMPTZ,
        deleted_by                      VARCHAR(50)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.cs_generated_courses IS '사용자가 저장한 놀러온나 생성 코스';
    COMMENT ON COLUMN public.cs_generated_courses.id IS '내부 생성 코스 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.cs_generated_courses.user_id IS '코스 저장 사용자 ID(FK)';
    COMMENT ON COLUMN public.cs_generated_courses.parent_course_id IS '재추천/복제 원본 코스 ID';
    COMMENT ON COLUMN public.cs_generated_courses.pair_id IS '같은 입력으로 생성된 형제 코스 묶음 ID';
    COMMENT ON COLUMN public.cs_generated_courses.weight_profile IS '추천 가중치 프로필';
    COMMENT ON COLUMN public.cs_generated_courses.title IS '생성 코스명';
    COMMENT ON COLUMN public.cs_generated_courses.input_signgu IS '사용자 입력 지역/시군구';
    COMMENT ON COLUMN public.cs_generated_courses.input_budget IS '사용자 입력 예산';
    COMMENT ON COLUMN public.cs_generated_courses.input_duration IS '사용자 입력 여행 시간';
    COMMENT ON COLUMN public.cs_generated_courses.input_companion IS '사용자 입력 동행 유형';
    COMMENT ON COLUMN public.cs_generated_courses.input_mood IS '사용자 입력 분위기/태그';
    COMMENT ON COLUMN public.cs_generated_courses.generation_mode IS '생성 모드';
    COMMENT ON COLUMN public.cs_generated_courses.generation_method IS '입력/생성 방식';
    COMMENT ON COLUMN public.cs_generated_courses.total_cost IS '예상 총 비용';
    COMMENT ON COLUMN public.cs_generated_courses.total_minutes IS '예상 총 소요시간(분)';
    COMMENT ON COLUMN public.cs_generated_courses.total_savings IS '예상 절약 금액';
    COMMENT ON COLUMN public.cs_generated_courses.compared_with_travel_course_id IS '비교 기준 공식 여행코스 ID';
    COMMENT ON COLUMN public.cs_generated_courses.weather_at_gen IS '코스 생성 시점 환경/날씨 스냅샷(JSONB)';
    COMMENT ON COLUMN public.cs_generated_courses.is_public IS '공개 여부';
    COMMENT ON COLUMN public.cs_generated_courses.share_token IS '공유 URL 토큰';
    COMMENT ON COLUMN public.cs_generated_courses.view_count IS '공유 코스 조회수';
    COMMENT ON COLUMN public.cs_generated_courses.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.cs_generated_courses.created_by IS '생성 주체(CreateAudit)';
    COMMENT ON COLUMN public.cs_generated_courses.updated_at IS '수정 시각(UpdateAudit)';
    COMMENT ON COLUMN public.cs_generated_courses.updated_by IS '수정 주체(UpdateAudit)';
    COMMENT ON COLUMN public.cs_generated_courses.deleted_at IS '소프트 삭제 시각(DeleteAudit)';
    COMMENT ON COLUMN public.cs_generated_courses.deleted_by IS '소프트 삭제 주체(DeleteAudit)';
    """)

    op.execute("""
    CREATE TABLE public.cs_generated_course_items (
        id                          BIGSERIAL   PRIMARY KEY,
        course_id                   BIGINT      NOT NULL
            REFERENCES public.cs_generated_courses(id) ON DELETE CASCADE,
        serial_num                  SMALLINT    NOT NULL CHECK (serial_num >= 1),
        spot_content_id             VARCHAR(20) NOT NULL
            REFERENCES public.sp_spots(content_id) ON DELETE RESTRICT,
        arrival_time                TIME,
        duration_minutes            SMALLINT
            CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
        expected_cost               INTEGER
            CHECK (expected_cost IS NULL OR expected_cost >= 0),
        travel_minutes_from_prev    SMALLINT
            CHECK (travel_minutes_from_prev IS NULL OR travel_minutes_from_prev >= 0),
        notes                       TEXT,
        created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by                  VARCHAR(50),
        updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_by                  VARCHAR(50),
        CONSTRAINT uk_cs_generated_course_items_serial UNIQUE (course_id, serial_num)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.cs_generated_course_items IS '사용자 저장 코스의 방문지 타임라인';
    COMMENT ON COLUMN public.cs_generated_course_items.id IS '내부 코스 아이템 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.cs_generated_course_items.course_id IS '생성 코스 ID(FK)';
    COMMENT ON COLUMN public.cs_generated_course_items.serial_num IS '코스 내 방문 순서(1부터)';
    COMMENT ON COLUMN public.cs_generated_course_items.spot_content_id IS '방문 스팟 TourAPI content_id(FK)';
    COMMENT ON COLUMN public.cs_generated_course_items.arrival_time IS '예상 도착 시각';
    COMMENT ON COLUMN public.cs_generated_course_items.duration_minutes IS '예상 체류 시간(분)';
    COMMENT ON COLUMN public.cs_generated_course_items.expected_cost IS '예상 비용';
    COMMENT ON COLUMN public.cs_generated_course_items.travel_minutes_from_prev IS '이전 장소로부터 이동 시간(분)';
    COMMENT ON COLUMN public.cs_generated_course_items.notes IS '타임라인 표시 메모';
    COMMENT ON COLUMN public.cs_generated_course_items.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.cs_generated_course_items.created_by IS '생성 주체(CreateAudit)';
    COMMENT ON COLUMN public.cs_generated_course_items.updated_at IS '수정 시각(UpdateAudit)';
    COMMENT ON COLUMN public.cs_generated_course_items.updated_by IS '수정 주체(UpdateAudit)';
    """)

    op.execute("""
    CREATE TABLE public.cs_course_decisions (
        id                          BIGSERIAL   PRIMARY KEY,
        course_id                   BIGINT      NOT NULL
            REFERENCES public.cs_generated_courses(id) ON DELETE CASCADE,
        decision_type               VARCHAR(20) NOT NULL
            CHECK (decision_type IN ('exclude', 'replace', 'boost')),
        severity                    VARCHAR(20) NOT NULL
            CHECK (severity IN ('critical', 'warning', 'info')),
        spot_content_id             VARCHAR(20)
            REFERENCES public.sp_spots(content_id) ON DELETE SET NULL,
        replacement_spot_id         VARCHAR(20)
            REFERENCES public.sp_spots(content_id) ON DELETE SET NULL,
        reason                      TEXT,
        user_message                TEXT,
        evidence                    JSONB,
        created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by                  VARCHAR(50)
    );
    """)

    op.execute("""
    COMMENT ON TABLE public.cs_course_decisions IS '코스 추천/대체/제외 의사결정 로그';
    COMMENT ON COLUMN public.cs_course_decisions.id IS '의사결정 로그 식별자(BIGSERIAL PK)';
    COMMENT ON COLUMN public.cs_course_decisions.course_id IS '생성 코스 ID(FK)';
    COMMENT ON COLUMN public.cs_course_decisions.decision_type IS '의사결정 타입(exclude/replace/boost)';
    COMMENT ON COLUMN public.cs_course_decisions.severity IS '중요도(critical/warning/info)';
    COMMENT ON COLUMN public.cs_course_decisions.spot_content_id IS '원본 후보 스팟 TourAPI content_id(FK)';
    COMMENT ON COLUMN public.cs_course_decisions.replacement_spot_id IS '대체 결과 스팟 TourAPI content_id(FK)';
    COMMENT ON COLUMN public.cs_course_decisions.reason IS '개발자/운영자용 상세 사유';
    COMMENT ON COLUMN public.cs_course_decisions.user_message IS '사용자 화면 표시용 메시지';
    COMMENT ON COLUMN public.cs_course_decisions.evidence IS '판단 근거 스냅샷(JSONB)';
    COMMENT ON COLUMN public.cs_course_decisions.created_at IS '생성 시각(CreateAudit)';
    COMMENT ON COLUMN public.cs_course_decisions.created_by IS '생성 주체(CreateAudit)';
    """)

    op.execute("""
    CREATE UNIQUE INDEX uk_cs_generated_courses_share_token
        ON public.cs_generated_courses (share_token)
        WHERE share_token IS NOT NULL;
    """)

    op.execute("""
    CREATE INDEX idx_cs_generated_courses_user_created
        ON public.cs_generated_courses (user_id, created_at DESC)
        WHERE deleted_at IS NULL;
    """)

    op.execute("""
    CREATE INDEX idx_cs_generated_courses_pair
        ON public.cs_generated_courses (pair_id)
        WHERE pair_id IS NOT NULL;
    """)

    op.execute("""
    CREATE INDEX idx_cs_generated_course_items_spot
        ON public.cs_generated_course_items (spot_content_id);
    """)

    op.execute("""
    CREATE INDEX idx_cs_course_decisions_course_created
        ON public.cs_course_decisions (course_id, created_at);
    """)

    op.execute("""
    CREATE TRIGGER trg_cs_generated_courses_updated_at
        BEFORE UPDATE ON public.cs_generated_courses
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)

    op.execute("""
    CREATE TRIGGER trg_cs_generated_course_items_updated_at
        BEFORE UPDATE ON public.cs_generated_course_items
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_cs_generated_course_items_updated_at "
        "ON public.cs_generated_course_items;"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_cs_generated_courses_updated_at ON public.cs_generated_courses;")
    op.execute("DROP INDEX IF EXISTS public.idx_cs_course_decisions_course_created;")
    op.execute("DROP INDEX IF EXISTS public.idx_cs_generated_course_items_spot;")
    op.execute("DROP INDEX IF EXISTS public.idx_cs_generated_courses_pair;")
    op.execute("DROP INDEX IF EXISTS public.idx_cs_generated_courses_user_created;")
    op.execute("DROP INDEX IF EXISTS public.uk_cs_generated_courses_share_token;")
    op.execute("DROP TABLE IF EXISTS public.cs_course_decisions;")
    op.execute("DROP TABLE IF EXISTS public.cs_generated_course_items;")
    op.execute("DROP TABLE IF EXISTS public.cs_generated_courses;")

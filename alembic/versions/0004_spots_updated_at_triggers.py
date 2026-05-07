"""auto-update updated_at on UPDATE for SPOTS domain tables

operation.md §11.3: updated_at 자동 갱신은 트리거 또는 애플리케이션 레벨.
공용 함수 set_updated_at()을 만들고, updated_at을 가진 모든 SPOTS 테이블에 부착.

대상 테이블 (updated_at 컬럼 보유):
- spots_core
- spot_details
- spot_embeddings
- spots_raw_snapshots

미대상 (updated_at 없음, INSERT-only 또는 created_at만):
- spot_images, spot_tags, spot_congestion_forecast

Revision ID: 0004_spots_updated_at_triggers
Revises: 0003_spots_indexes
Create Date: 2026-04-27

체인 reorder: 외부 FK(0005)는 master 테이블이 들어와야 적용 가능하므로,
master 의존이 없는 트리거를 0004로 앞당겨 SPOTS 단독으로 진행 가능하게 함.
"""
from __future__ import annotations

from alembic import op

revision = "0004_spots_updated_at_triggers"
down_revision = "0003_spots_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 공용 함수 — 다른 도메인에서도 같은 함수를 재사용할 수 있도록 도메인 prefix 없이 명명.
    # 이미 존재하면 OR REPLACE로 무해하게 갱신.
    op.execute("""
    CREATE OR REPLACE FUNCTION set_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    for table in (
        "spots_core",
        "spot_details",
        "spot_embeddings",
        "spots_raw_snapshots",
    ):
        op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    for table in (
        "spots_raw_snapshots",
        "spot_embeddings",
        "spot_details",
        "spots_core",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    # 다른 도메인이 같은 함수를 쓸 가능성 → 함수 자체는 DROP하지 않는다.
    # 정말 SPOTS 단독으로 깔끔히 떼어내려면 아래 라인 주석 해제.
    # op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
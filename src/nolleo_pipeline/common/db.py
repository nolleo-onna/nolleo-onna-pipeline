"""PostgreSQL 비동기 커넥션 풀.

[이 파일이 왜 있냐]
- 매 쿼리마다 connect/disconnect 하면 느림 → "풀(pool)"에 커넥션을 미리 잡아둠
- 파이프라인 어디서든 같은 풀을 쓰도록 싱글턴 패턴
- psycopg 3.x는 모던 PG 드라이버. asyncio 지원.
"""

from __future__ import annotations

import os

from psycopg.rows import dict_row  # SELECT 결과를 tuple이 아닌 dict로 받기
from psycopg_pool import AsyncConnectionPool

# 모듈 레벨 변수 — 처음 한 번만 만들고 이후 재사용.
# `_pool`처럼 _로 시작하면 "외부에서 직접 건드리지 마" 관용 표시.
_pool: AsyncConnectionPool | None = None


def build_dsn() -> str:
    """DB 접속 문자열(DSN)을 환경변수에서 읽는다."""
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL 환경변수가 필요합니다.")
    return dsn


async def get_pool() -> AsyncConnectionPool:
    """공유 커넥션 풀을 반환. 처음 호출 시 생성, 이후엔 재사용.
    매번 db 연결하는 비용을 줄임. 
    """
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=build_dsn(),
            min_size=1,  # 항상 살아있는 커넥션 최소
            max_size=10, # 동시에 최대 몇 개까지 열 수 있나
            kwargs={"row_factory": dict_row}, 
            # SELECT는 dict로 받음/ sql 조회 결과를 튜플이 아니라 
            # 딕셔너리 형태로 받음.
            open=False, # 명시적으로 open() 호출 시점에 연다
        )
        await _pool.open() # 실제 연결 수립
    return _pool

async def close_pool() -> None:
    """커넥션 풀을 닫는다. 프로그램 종료 시 한 번만 호출."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

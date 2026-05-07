"""PostgreSQL 비동기 커넥션 풀.

[이 파일이 왜 있냐]
- 매 쿼리마다 connect/disconnect 하면 느림 → "풀(pool)"에 커넥션을 미리 잡아둠
- 파이프라인 어디서든 같은 풀을 쓰도록 싱글턴 패턴
- psycopg 3.x는 모던 PG 드라이버. asyncio 지원.
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from nolleo_pipeline.config import get_settings

_pool: AsyncConnectionPool | None = None


def build_dsn() -> str:
    """DB 접속 문자열을 settings에서 가져온다.
    이전엔 os.getenv("DATABASE_URL") 직접 읽었지만, .env에 그 키가 없고
    설정 로더 단일화 원칙에 어긋나서 get_settings() 경유로 변경.
    """
    return get_settings().psycopg_dsn


async def get_pool() -> AsyncConnectionPool:
    """공유 커넥션 풀. 처음 호출 시 생성, 이후 재사용."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=build_dsn(),
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await _pool.open()
    return _pool


async def close_pool() -> None:
    """커넥션 풀을 닫는다. 프로그램 종료 시 한 번만 호출."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

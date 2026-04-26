"""PostgreSQL 커넥션 풀 (psycopg 3.x async)."""

from psycopg_pool import AsyncConnectionPool

# TODO: AsyncConnectionPool 인스턴스 생성
# TODO: 트랜잭션 컨텍스트 매니저 헬퍼
# TODO: dict_row 기본 적용


async def get_pool() -> AsyncConnectionPool:
    """공유 커넥션 풀을 반환한다."""
    raise NotImplementedError


"""Alembic environment (async psycopg).

[설계 원칙]
- DB 접속 정보는 nolleo_pipeline.config.get_settings() 단일 진입점만 통한다.
- alembic.ini의 sqlalchemy.url은 env.py에서 덮어쓰므로 그 값은 무시된다.
- ORM 모델을 안 쓰므로 target_metadata = None (autogenerate 미사용).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from nolleo_pipeline.config import get_settings

# Alembic Config 객체. alembic.ini의 [alembic] 섹션이 여기에 들어옴.
config = context.config

# 로깅 설정 (alembic.ini의 [loggers] 등을 적용)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#  DB URL을 settings에서 주입.
#    .env의 DB_HOST/PORT/NAME/USER/PASSWORD를 조합해 sqlalchemy_database_uri 만들어 사용.
#    alembic.ini의 하드코딩 값은 여기서 무효화됨.
config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_database_uri)

# autogenerate 미사용 → None.
# 향후 SQLAlchemy 모델로 자동 비교를 켤 거면 Base.metadata 연결.
target_metadata = None


def run_migrations_offline() -> None:
    """오프라인 모드: 실제 DB 연결 없이 SQL 스크립트만 출력.
    `alembic upgrade head --sql` 같은 명령에서 사용.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """동기 컨텍스트에서 실제 마이그레이션 실행."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인 모드: 실제 DB에 연결하고 적용 (`alembic upgrade head`).

    async psycopg 드라이버를 쓰므로 async_engine_from_config 경유.
    poolclass=NullPool: alembic은 1회성 작업이라 풀 불필요.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async def _run() -> None:
        async with connectable.connect() as connection:
            # alembic 본체는 동기 API라 run_sync로 감싸 호출.
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
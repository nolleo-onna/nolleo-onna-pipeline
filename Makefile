.PHONY: install db-up db-down migrate migrate-down migrate-history db-shell db-current test lint format

# .env를 자동 로드해서 모든 타겟이 같은 DB를 본다.
include .env
export

install:
	uv sync

db-up:
	docker compose up -d

db-down:
	docker compose down

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1

migrate-history:
	uv run alembic history

# .env의 DB_*로 RDS(또는 로컬)에 psql 접속.
db-shell:
	PGPASSWORD=$(DB_PASSWORD) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d $(DB_NAME)

# 현재 적용된 alembic revision 확인 (psql 통해 직접 조회).
db-current:
	PGPASSWORD=$(DB_PASSWORD) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d $(DB_NAME) \
		-c "SELECT version_num FROM alembic_version;"

test:
	pytest

lint:
	ruff check .
	mypy .

format:
	ruff format .

.PHONY: install db-up db-down migrate migrate-down test lint format

install:
	uv sync

db-up:
	docker compose up -d

db-down:
	docker compose down

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

test:
	pytest

lint:
	ruff check .
	mypy .

format:
	ruff format .

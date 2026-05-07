# 놀러온나 데이터 파이프라인

놀러온나 서비스의 데이터 파이프라인 레포로, TourAPI/부산 공공데이터/외부 API를 수집·정규화해 PostgreSQL(PostGIS, pgvector, pg_trgm)에 적재하는 배치 시스템입니다. 본 레포는 데이터 적재에 집중하며, 서비스 API(Spring)는 별도 레포에서 운영합니다.

## 기술 스택

- Python 3.11+
- uv (패키지/실행 관리)
- PostgreSQL 16+, PostGIS, pgvector, pg_trgm
- psycopg 3.x (`psycopg[binary,pool]`)
- httpx (async), tenacity
- pydantic v2, pydantic-settings정
- Alembic
- OpenAI (`text-embedding-3-small`, `gpt-4o-mini`)
- APScheduler
- structlog
- pytest, pytest-asyncio, ruff, mypy

## 로컬 개발 시작하기

```bash
# 1) 로컬 DB 실행
docker compose up -d

# 2) 의존성 설치
uv sync

# 3) 마이그레이션 적용
alembic upgrade head
```

## 디렉토리 구조

```text
nolleo-onna-pipeline/
├── alembic/
├── docs/
├── src/nolleo_pipeline/
│   ├── domains/
│   ├── llm/
│   ├── jobs/
│   └── common/
├── tests/
└── scripts/
```

## 주요 명령어

```bash
make install
make db-up
make migrate
make test
make lint
make format
```

## 문서 안내

- ERD: `docs/erd.md`
- 운영 정책: `docs/operation.md`
- 제안서: `docs/proposal.md`

## 기여 가이드 (간단)

- 브랜치: `feature/<topic>`, `fix/<topic>`, `chore/<topic>`
- PR은 작은 단위로 나누고, 스키마 변경 시 Alembic 리비전과 함께 제출
- 본 레포에서는 데이터 파이프라인 코드와 운영 문서 정합성을 우선 유지
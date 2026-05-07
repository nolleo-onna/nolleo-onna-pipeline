-- 매니지드 PG는 콘솔/파라미터에서, 자가 운영은 superuser로 1회 실행.
-- dev: docker-compose의 /docker-entrypoint-initdb.d/ 에 마운트하면 자동.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
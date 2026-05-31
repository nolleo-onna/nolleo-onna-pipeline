-- Reset helper: drop all tables in the public schema.
-- Intended for dev/rebootstrap workflows only.
-- Extensions (postgis/vector/pg_trgm) are not removed by this script.
--
-- Usage:
--   psql "$DATABASE_URL" -f scripts/db/01_drop_all_tables.sql
-- or
--   psql "host=... port=... dbname=... user=... sslmode=require" \
--     -f scripts/db/01_drop_all_tables.sql

BEGIN;

DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT quote_ident(n.nspname) AS schema_name,
               quote_ident(c.relname) AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'  -- ordinary tables only
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass
                AND d.objid = c.oid
                AND d.deptype = 'e'  -- extension-owned object
          )
        ORDER BY c.relname
    LOOP
        EXECUTE format(
            'DROP TABLE IF EXISTS %s.%s CASCADE;',
            rec.schema_name,
            rec.table_name
        );
    END LOOP;
END
$$;

COMMIT;

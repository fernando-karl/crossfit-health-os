-- Transfer ownership of all public-schema tables (and their indexes/sequences)
-- from `postgres` to `crossfit` so the runtime role can run Alembic migrations.
--
-- Why: tables created in early migrations were owned by `postgres`; later
-- migrations created their tables as `crossfit`. The mismatch blocks
-- ALTER TABLE statements (migrations 0012/0013/0014 fail with
-- "must be owner of table users").
--
-- Run once as a superuser (postgres) BEFORE the next `alembic upgrade head`:
--
--     PGPASSWORD=<postgres_pw> psql -h <host> -U postgres -d <db> \
--         -f backend/scripts/transfer_table_ownership.sql
--
-- Idempotent — safe to re-run.

DO $$
DECLARE
    r RECORD;
    new_owner TEXT := 'crossfit';
BEGIN
    -- Tables (and the alembic_version housekeeping table)
    FOR r IN
        SELECT tablename
          FROM pg_tables
         WHERE schemaname = 'public'
           AND tableowner <> new_owner
    LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO %I', r.tablename, new_owner);
        RAISE NOTICE 'altered table %', r.tablename;
    END LOOP;

    -- Sequences (e.g. users_id_seq) — owner usually follows the table,
    -- but transfer them explicitly to be safe.
    FOR r IN
        SELECT c.relname AS seq_name
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_roles    o ON o.oid = c.relowner
         WHERE c.relkind = 'S'
           AND n.nspname = 'public'
           AND o.rolname <> new_owner
    LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO %I', r.seq_name, new_owner);
        RAISE NOTICE 'altered sequence %', r.seq_name;
    END LOOP;

    -- Views, if any.
    FOR r IN
        SELECT viewname
          FROM pg_views
         WHERE schemaname = 'public'
           AND viewowner <> new_owner
    LOOP
        EXECUTE format('ALTER VIEW public.%I OWNER TO %I', r.viewname, new_owner);
        RAISE NOTICE 'altered view %', r.viewname;
    END LOOP;
END $$;

-- Sanity check: should now report 0 tables not owned by `crossfit`.
SELECT COUNT(*) AS tables_still_not_owned_by_crossfit
  FROM pg_tables
 WHERE schemaname = 'public' AND tableowner <> 'crossfit';

#!/usr/bin/env bash
# ============================================================
# Restore Timescale Cloud fork dump into local Docker DB
# Preserves hypertables + compression. Handles RLS.
#
# Usage:
#   ./backend/scripts/restore_from_fork.sh <dump_file>
#
# Prerequisites:
#   - Docker running (docker compose up -d)
#   - pg_dump/pg_restore installed locally (PostgreSQL 16+)
#   - Dump created with:
#       pg_dump "postgresql://tsdbadmin:SENHA@HOST:PORT/tsdb?sslmode=require" \
#         --format=custom --no-owner --no-privileges \
#         --exclude-schema='_timescaledb_*' \
#         --exclude-schema='timescale_functions' \
#         --exclude-schema='_osm_*' \
#         --exclude-schema='toolkit_experimental' \
#         -f db_dump_data.dump
# ============================================================

set -euo pipefail

DUMP_FILE="${1:?Usage: $0 <dump_file>}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5434}"
DB_USER="${DB_USER:-netz}"
DB_NAME="${DB_NAME:-netz_engine}"
CONTAINER="${CONTAINER:-netz-analysis-engine-db-1}"

if [ ! -f "$DUMP_FILE" ]; then
  echo "ERROR: Dump file not found: $DUMP_FILE"
  exit 1
fi

echo "=== Phase 1: Disable RLS on all protected tables ==="
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT 'ALTER TABLE public.' || quote_ident(relname) || ' DISABLE ROW LEVEL SECURITY;'
   FROM pg_class
   WHERE relnamespace = 'public'::regnamespace AND relrowsecurity = true
   ORDER BY relname;" \
  | docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"

echo "=== Phase 2: Disable triggers (FK constraints) ==="
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SET session_replication_role = 'replica';"

echo "=== Phase 3: Restore data ==="
pg_restore \
  --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="$DB_NAME" \
  --data-only --no-owner --no-privileges \
  --disable-triggers \
  --jobs=4 \
  --verbose \
  "$DUMP_FILE" 2>&1 | tee restore_data.log

echo "=== Phase 4: Re-enable RLS on all protected tables ==="
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT 'ALTER TABLE public.' || quote_ident(relname) || ' ENABLE ROW LEVEL SECURITY;'
   FROM pg_class
   WHERE relnamespace = 'public'::regnamespace
     AND relrowsecurity = false
     AND EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = relname AND p.schemaname = 'public')
   ORDER BY relname;" \
  | docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"

# Also re-enable FORCE RLS where applicable (check alembic migrations for which tables use FORCE)
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
-- Re-enable FORCE RLS on tables that had it (all except dd_chapters, dd_reports, instruments_org, macro_reviews)
DO \$\$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT tablename FROM pg_policies WHERE schemaname = 'public'
    GROUP BY tablename
  LOOP
    -- Skip tables that use NO FORCE (migration 0062)
    IF tbl NOT IN ('dd_chapters', 'dd_reports', 'instruments_org', 'macro_reviews') THEN
      EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tbl);
    END IF;
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
  END LOOP;
END;
\$\$;
"

echo "=== Phase 5: Refresh materialized views ==="
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
REFRESH MATERIALIZED VIEW IF EXISTS mv_unified_funds;
REFRESH MATERIALIZED VIEW IF EXISTS mv_unified_assets;
REFRESH MATERIALIZED VIEW IF EXISTS mv_macro_latest;
REFRESH MATERIALIZED VIEW IF EXISTS mv_macro_regional_summary;
REFRESH MATERIALIZED VIEW IF EXISTS sec_insider_sentiment;
"

echo "=== Phase 6: Verify ==="
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 'RLS tables' as check, COUNT(*) as count FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relrowsecurity = true
UNION ALL
SELECT 'FORCE RLS tables', COUNT(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relforcerowsecurity = true
UNION ALL
SELECT 'Hypertables', COUNT(*) FROM timescaledb_information.hypertables
UNION ALL
SELECT 'Mat views', COUNT(*) FROM pg_matviews WHERE schemaname = 'public';
"

echo "=== DONE ==="

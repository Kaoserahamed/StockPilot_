#!/bin/bash
# StockPilot Database Maintenance Script
# Usage: ./scripts/db-maintenance.sh
# Rebuilds indexes, updates statistics, and vacuums tables

set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-stockpilot}"
DB_USER="${DB_USER:-stockpilot}"

# SECURITY: No default password is provided - script will fail if DB_PASSWORD
# is not set in the environment. Password is passed via connection string.
: "${DB_PASSWORD:?DB_PASSWORD is not set. Export it before running this script; no default password is provided.}"

# Use connection string to avoid exposing password in environment
DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "[maintenance] Starting database maintenance on ${DB_NAME}..."

# Reindex all tables
echo "[maintenance] Reindexing database..."
psql "$DB_URL" -c "REINDEX DATABASE $DB_NAME;" 2>/dev/null

# Update statistics
echo "[maintenance] Updating statistics..."
psql "$DB_URL" -c "ANALYZE;" 2>/dev/null

# Vacuum all tables
echo "[maintenance] Vacuuming..."
psql "$DB_URL" -c "VACUUM ANALYZE;" 2>/dev/null

# Show table sizes
echo "[maintenance] Table sizes:"
psql "$DB_URL" -c "
SELECT schemaname, tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables WHERE schemaname='public' ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
" 2>/dev/null

echo "[maintenance] Complete."


#!/bin/bash
# StockPilot Database Backup Script
# Usage: ./scripts/backup-db.sh [backup_dir]
# Environment variables (or defaults):
#   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-stockpilot}"
DB_USER="${DB_USER:-stockpilot}"
BACKUP_DIR="${1:-./backups}"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="stockpilot_${DATE}.sql.gz"

# SECURITY: There is deliberately NO default password. A silent placeholder
# fallback would produce confusing authentication errors against production
# and leak a weak credential into shell history and process listings.
# Password is passed via connection string to avoid PGPASSWORD environment exposure.
: "${DB_PASSWORD:?DB_PASSWORD is not set. Export it before running this script; no default password is provided.}"

mkdir -p "$BACKUP_DIR"

# Use connection string to avoid exposing password in environment
DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "[backup] Starting backup of ${DB_NAME}..."
pg_dump \
  "$DB_URL" \
  --format=custom --compress=9 --verbose \
  | gzip > "${BACKUP_DIR}/${FILENAME}"

echo "[backup] Complete: ${BACKUP_DIR}/${FILENAME}"
ls -lh "${BACKUP_DIR}/${FILENAME}"


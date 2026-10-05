#!/bin/bash
# StockPilot Database Restore Script
# Usage: ./scripts/restore-db.sh <backup_file>
# Environment variables (or defaults):
#   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-stockpilot}"
DB_USER="${DB_USER:-stockpilot}"

# SECURITY: No default password is provided - script will fail if DB_PASSWORD
# is not set in the environment. Password is passed via connection string.
: "${DB_PASSWORD:?DB_PASSWORD is not set. Export it before running this script; no default password is provided.}"

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <backup_file>"
  exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "[restore] Error: File not found: $BACKUP_FILE"
  exit 1
fi

echo "[restore] WARNING: This will REPLACE the current database: ${DB_NAME}"
read -p "Are you sure? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "[restore] Aborted."
  exit 0
fi

# Use connection string to avoid exposing password in environment
DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "[restore] Restoring from ${BACKUP_FILE}..."
gunzip -c "$BACKUP_FILE" | pg_restore \
  "$DB_URL" \
  --clean --if-exists --no-owner --no-privileges \
  -

echo "[restore] Complete."


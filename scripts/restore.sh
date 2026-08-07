#!/usr/bin/env bash
#
# Cisco Security Automation Platform - restore
# Usage:  ./scripts/restore.sh backups/csap-db-<stamp>.sql.gz [backups/csap-data-<stamp>.tar.gz]
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_DUMP="${1:-}"
DATA_ARCHIVE="${2:-}"

log()  { printf '\033[1;34m[csap]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[csap]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -f "$DB_DUMP" ]] || die "Usage: ./scripts/restore.sh <db-dump.sql.gz> [data-archive.tar.gz]"

read -rp "This overwrites the current CSAP database. Type 'restore' to continue: " CONFIRM
[[ "$CONFIRM" == "restore" ]] || die "Aborted."

# shellcheck disable=SC1091
set -a; source .env; set +a

log "Stopping application services (database stays up)..."
docker compose stop backend worker frontend

log "Restoring database from $DB_DUMP..."
gunzip -c "$DB_DUMP" | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

if [[ -n "$DATA_ARCHIVE" && -f "$DATA_ARCHIVE" ]]; then
  log "Restoring artifacts from $DATA_ARCHIVE..."
  docker run --rm \
    -v csap_csap_data:/data \
    -v "$(cd "$(dirname "$DATA_ARCHIVE")" && pwd)":/backup:ro \
    alpine:3.20 sh -c "rm -rf /data/* && tar xzf /backup/$(basename "$DATA_ARCHIVE") -C /data"
fi

log "Starting services..."
docker compose up -d
log "Restore complete."

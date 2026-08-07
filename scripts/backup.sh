#!/usr/bin/env bash
#
# Cisco Security Automation Platform - backup (database + generated artifacts)
# Usage:  ./scripts/backup.sh [output-directory]
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-$ROOT_DIR/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
# A backup contains encrypted device credentials, the key that decrypts them and
# the admin password hash. Nobody but the owner should be able to read it.
chmod 700 "$OUT_DIR"
umask 077

log() { printf '\033[1;34m[csap]\033[0m %s\n' "$*"; }

# shellcheck disable=SC1091
set -a; source .env; set +a

log "Dumping PostgreSQL..."
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  | gzip > "$OUT_DIR/csap-db-$STAMP.sql.gz"

log "Archiving generated artifacts..."
# The archive is created by root inside the container, so it is locked down there
# too - the host chmod below cannot touch a root-owned file.
docker run --rm \
  -v csap_csap_data:/data:ro \
  -v "$OUT_DIR":/backup \
  alpine:3.20 sh -c \
  "tar czf /backup/csap-data-$STAMP.tar.gz -C /data . && chmod 600 /backup/csap-data-$STAMP.tar.gz" \
  2>/dev/null || true

cp .env "$OUT_DIR/csap-env-$STAMP.bak"
chmod 600 "$OUT_DIR"/csap-*-"$STAMP".* "$OUT_DIR/csap-env-$STAMP.bak" 2>/dev/null || true

log "Backup written to $OUT_DIR (db + data + .env, stamp $STAMP)"
find "$OUT_DIR" -name 'csap-*' -mtime +30 -delete 2>/dev/null || true

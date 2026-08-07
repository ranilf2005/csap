#!/usr/bin/env bash
#
# Cisco Security Automation Platform - uninstall
# Usage:  ./scripts/uninstall.sh [--purge]
#         --purge also deletes the database volume and all captured data.
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PURGE=false
[[ "${1:-}" == "--purge" ]] && PURGE=true

log() { printf '\033[1;34m[csap]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[csap]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "$PURGE" == true ]]; then
  echo "This permanently deletes the CSAP database, snapshots and generated reports."
  read -rp "Type 'DELETE' to confirm: " CONFIRM
  [[ "$CONFIRM" == "DELETE" ]] || die "Aborted."
  log "Taking a final backup first..."
  ./scripts/backup.sh || log "Backup skipped (stack may already be down)."
  docker compose down -v --remove-orphans
  log "Stack and volumes removed. Your .env and backups/ directory were left in place."
else
  docker compose down --remove-orphans
  log "Containers stopped. Data volumes kept. Use --purge to delete data as well."
fi

#!/usr/bin/env bash
#
# Cisco Security Automation Platform - upgrade
# Usage:  ./scripts/upgrade.sh [<version>]
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

log()  { printf '\033[1;34m[csap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[csap]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[csap]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -f .env ]] || die "No .env found. Run ./scripts/install.sh first."
TARGET_VERSION="${1:-}"

# shellcheck disable=SC1091
set -a; source .env; set +a
CURRENT_VERSION="$CSAP_VERSION"

log "Backing up before upgrading..."
./scripts/backup.sh

if [[ -n "$TARGET_VERSION" ]]; then
  log "Switching CSAP_VERSION ${CURRENT_VERSION} -> ${TARGET_VERSION}"
  python3 - "$TARGET_VERSION" <<'PY'
import re, sys
version = sys.argv[1]
with open(".env", encoding="utf-8") as fh:
    text = fh.read()
text = re.sub(r"^CSAP_VERSION=.*$", f"CSAP_VERSION={version}", text, count=1, flags=re.M)
with open(".env", "w", encoding="utf-8") as fh:
    fh.write(text)
PY
  set -a; source .env; set +a
fi

log "Pulling images for ${CSAP_VERSION}..."
docker compose pull

log "Recreating services (schema migrations run in the backend entrypoint)..."
docker compose up -d --remove-orphans

log "Waiting for health..."
sleep 20
if curl -ksSf "https://localhost:${HTTPS_PORT:-443}/api/v1/health/live" >/dev/null 2>&1; then
  log "Upgrade to ${CSAP_VERSION} complete."
else
  warn "Health check failed. Roll back with: ./scripts/upgrade.sh ${CURRENT_VERSION}"
  warn "Then restore data with: ./scripts/restore.sh <backup-file>"
  exit 1
fi

log "Pruning unused images..."
docker image prune -f >/dev/null 2>&1 || true

#!/usr/bin/env bash
#
# Cisco Security Automation Platform - installer
# Usage:  ./scripts/install.sh [--build] [--hostname <fqdn-or-ip>]
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BUILD_LOCAL=false
HOSTNAME_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)    BUILD_LOCAL=true; shift ;;
    --hostname) HOSTNAME_OVERRIDE="$2"; shift 2 ;;
    -h|--help)  sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

log()  { printf '\033[1;34m[csap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[csap]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[csap]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. prerequisites ------------------------------------------------------
log "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || die "Docker is not installed. See https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is required (docker compose v2)."
docker info >/dev/null 2>&1 || die "Cannot talk to the Docker daemon. Is it running, and is your user in the 'docker' group?"
command -v openssl >/dev/null 2>&1 || die "openssl is required to generate secrets and certificates."

# --- 2. environment file ---------------------------------------------------
gen_hex()    { openssl rand -hex 32; }
gen_fernet() { openssl rand -base64 32 | tr '+/' '-_'; }   # url-safe base64, 44 chars
gen_pass()   { openssl rand -base64 24 | tr -d '/+=' | cut -c1-24; }

if [[ ! -f .env ]]; then
  log "Creating .env with freshly generated secrets..."
  cp .env.example .env

  ADMIN_PASSWORD="$(gen_pass)"
  set_var() { # portable in-place edit
    local key="$1" value="$2"
    python3 - "$key" "$value" <<'PY'
import os, re, sys
key, value = sys.argv[1], sys.argv[2]
with open(".env", encoding="utf-8") as fh:
    text = fh.read()
text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, count=1, flags=re.M)
with open(".env", "w", encoding="utf-8") as fh:
    fh.write(text)
PY
  }
  command -v python3 >/dev/null 2>&1 || die "python3 is required by the installer to write .env safely."

  set_var SECRET_KEY                "$(gen_hex)"
  set_var CREDENTIAL_ENCRYPTION_KEY "$(gen_fernet)"
  set_var POSTGRES_PASSWORD         "$(gen_pass)"
  set_var REDIS_PASSWORD            "$(gen_pass)"
  set_var CSAP_ADMIN_PASSWORD       "$ADMIN_PASSWORD"
  [[ -n "$HOSTNAME_OVERRIDE" ]] && set_var PUBLIC_URL "https://$HOSTNAME_OVERRIDE"

  chmod 600 .env
  NEW_INSTALL=true
else
  warn ".env already exists - keeping your existing configuration and secrets."
  NEW_INSTALL=false
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

# --- 3. TLS certificate ----------------------------------------------------
# The nginx image runs entirely as uid 101, so it must own the key to read it.
NGINX_UID=101

grant_cert_access() {
  if docker run --rm -v "$ROOT_DIR/nginx/certs:/certs" alpine:3.20 \
       chown -R "${NGINX_UID}:${NGINX_UID}" /certs >/dev/null 2>&1; then
    return 0
  fi
  warn "Could not chown the certificates to uid ${NGINX_UID}; falling back to world-readable."
  chmod 644 nginx/certs/csap.key nginx/certs/csap.crt
}

CERT_CN="${HOSTNAME_OVERRIDE:-$(hostname -f 2>/dev/null || hostname)}"
if [[ ! -f nginx/certs/csap.crt ]]; then
  log "Generating a self-signed TLS certificate for '$CERT_CN' (replace with a CA-signed cert for production)..."
  mkdir -p nginx/certs
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout nginx/certs/csap.key -out nginx/certs/csap.crt \
    -subj "/C=US/O=Cisco Security Automation Platform/CN=${CERT_CN}" \
    -addext "subjectAltName=DNS:${CERT_CN},DNS:localhost,IP:127.0.0.1" 2>/dev/null
  chmod 600 nginx/certs/csap.key
fi
grant_cert_access

# --- 4. images -------------------------------------------------------------
if [[ "$BUILD_LOCAL" == true ]]; then
  log "Building images locally..."
  docker compose build --pull
else
  log "Pulling published images (${REGISTRY}/${IMAGE_NAMESPACE}, tag ${CSAP_VERSION})..."
  docker compose pull || {
    warn "Pull failed - falling back to a local build."
    docker compose build --pull
  }
fi

# --- 5. start --------------------------------------------------------------
log "Starting the platform..."
docker compose up -d

log "Waiting for services to become healthy..."
for _ in $(seq 1 60); do
  if docker compose ps --format json | grep -q '"Health":"healthy"'; then
    sleep 5
    break
  fi
  sleep 5
done

if curl -ksSf "https://localhost:${HTTPS_PORT:-443}/api/v1/health/live" >/dev/null 2>&1; then
  log "Health check passed."
else
  warn "Health check did not pass yet. Inspect logs with: docker compose logs -f"
fi

# --- 6. summary ------------------------------------------------------------
echo
log "Cisco Security Automation Platform ${CSAP_VERSION} is running."
echo "  URL:   ${PUBLIC_URL:-https://localhost}"
echo "  Login: ${CSAP_ADMIN_EMAIL}"
if [[ "$NEW_INSTALL" == true ]]; then
  echo "  Password: ${CSAP_ADMIN_PASSWORD}"
  echo
  warn "Store this password now - it is also in .env (chmod 600). Change it after first login."
fi
echo
echo "  Logs:    docker compose logs -f"
echo "  Stop:    docker compose down"
echo "  Upgrade: ./scripts/upgrade.sh"

#!/usr/bin/env sh
set -eu

ROLE="${CSAP_ROLE:-api}"

if [ "$ROLE" = "api" ]; then
    echo "[entrypoint] initialising database schema and seed data..."
    python -m app.bootstrap
    echo "[entrypoint] starting API server..."
    # Trust forwarded headers only from the reverse proxy on the compose network.
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
        --proxy-headers --forwarded-allow-ips="${TRUSTED_PROXY_IPS:-172.16.0.0/12,192.168.0.0/16,10.0.0.0/8}"
elif [ "$ROLE" = "worker" ]; then
    echo "[entrypoint] starting Celery worker..."
    exec celery -A app.workers.celery_app.celery_app worker --loglevel="${LOG_LEVEL:-INFO}" --concurrency="${WORKER_CONCURRENCY:-4}"
elif [ "$ROLE" = "beat" ]; then
    echo "[entrypoint] starting Celery beat..."
    exec celery -A app.workers.celery_app.celery_app beat --loglevel="${LOG_LEVEL:-INFO}"
else
    echo "[entrypoint] unknown CSAP_ROLE '$ROLE' (expected api|worker|beat)" >&2
    exit 1
fi

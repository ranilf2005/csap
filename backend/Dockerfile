# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user; /data is the shared reports/uploads volume.
RUN useradd --create-home --uid 10001 csap \
 && mkdir -p /data \
 && chown -R csap:csap /app /data \
 && chmod +x /app/entrypoint.sh

USER csap
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]

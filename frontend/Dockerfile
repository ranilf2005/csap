# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Vendor UI assets at build time so runtime never needs internet access.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && mkdir -p /app/app/static/vendor \
 && curl -fsSL -o /app/app/static/vendor/bootstrap.min.css https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css \
 && curl -fsSL -o /app/app/static/vendor/bootstrap.bundle.min.js https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js \
 && curl -fsSL -o /app/app/static/vendor/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js \
 && curl -fsSL -o /app/app/static/vendor/chart.umd.min.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY . .

RUN useradd --create-home --uid 10002 csapui && chown -R csapui:csapui /app
USER csapui

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]

---
title: Administration
nav_order: 12
---

# Administration

## Day-to-day commands

| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Logs (all) | `docker compose logs -f` |
| Logs (one service) | `docker compose logs -f backend` |
| Restart a service | `docker compose restart worker` |
| Stop (keep data) | `docker compose down` |
| Start | `docker compose up -d` |
| Shell in the backend | `docker compose exec backend sh` |
| Database shell | `docker compose exec postgres psql -U csap -d csap` |

`make help` lists the same operations as Make targets.

## Backups

```bash
./scripts/backup.sh                 # writes to ./backups
./scripts/backup.sh /mnt/nfs/csap   # or anywhere else
```

Each run produces three files stamped with the UTC time:
- `csap-db-<stamp>.sql.gz` — full PostgreSQL dump
- `csap-data-<stamp>.tar.gz` — uploaded workbooks and generated reports
- `csap-env-<stamp>.bak` — a copy of `.env` (mode `0600`)

Backups older than 30 days in the target directory are pruned automatically.

Schedule it:

```bash
(crontab -l 2>/dev/null; echo "15 2 * * * cd /opt/csap && ./scripts/backup.sh >> /var/log/csap-backup.log 2>&1") | crontab -
```

### Restore

```bash
./scripts/restore.sh backups/csap-db-<stamp>.sql.gz backups/csap-data-<stamp>.tar.gz
```

You must type `restore` to confirm. Application services stop, the database is replaced,
artifacts are restored, then everything starts again.

> Restoring a database taken with a **different** `CREDENTIAL_ENCRYPTION_KEY` leaves stored device
> credentials undecryptable. Restore the matching `.env` backup, or re-enter the passwords.

## Upgrades

```bash
git pull                      # REQUIRED FIRST - see below
./scripts/upgrade.sh          # moves to the version in the VERSION file
./scripts/upgrade.sh 0.4.0    # or a specific version
```

> **`git pull` first, every time.** Your `.env` pins `CSAP_VERSION` from install time and git
> never rewrites it, because it holds your secrets. `docker compose pull` on its own therefore
> re-fetches the version you already have. `upgrade.sh` reads the `VERSION` file from the
> checkout and rewrites `CSAP_VERSION` in `.env` for you - but only if the checkout is current.

The script backs up first, pulls the new images, recreates the services (schema changes run in the
backend entrypoint) and health-checks. If the health check fails it tells you how to roll back:

```bash
./scripts/upgrade.sh <previous-version>
./scripts/restore.sh backups/csap-db-<stamp>.sql.gz
```

To check what is actually running:

```bash
curl -k https://localhost/api/v1/health/live   # reports the running version
docker compose images | grep csap              # the image tags in use
```

## Secrets

All secrets live in `.env` (mode `0600`, git-ignored).

| Variable | Purpose | Rotatable? |
|---|---|---|
| `SECRET_KEY` | Signs JWTs and UI session cookies | Yes — invalidates all sessions |
| `CREDENTIAL_ENCRYPTION_KEY` | Encrypts stored device passwords | **No** — see below |
| `POSTGRES_PASSWORD` | Database | Yes, with care |
| `REDIS_PASSWORD` | Queue | Yes |

### Rotating SECRET_KEY

```bash
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env
docker compose up -d --force-recreate backend frontend
```

Everyone is signed out. No data is affected.

### CREDENTIAL_ENCRYPTION_KEY

**Back this up. If you lose it, every stored device password becomes unrecoverable** and you
must re-enter credentials for every registered system.

To rotate it deliberately: delete and re-add each system with its password after changing the key.
There is no automated re-encryption yet.

## Users

Version 0.3 ships a single administrator, seeded from `CSAP_ADMIN_EMAIL` / `CSAP_ADMIN_PASSWORD`
on first start. Change the password through the UI immediately after installing.
Multi-user accounts, roles and SSO are on the roadmap for 1.0.

To reset a forgotten admin password:

```bash
docker compose exec backend python -c "
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User
db = SessionLocal()
u = db.query(User).filter(User.email=='admin@example.com').first()
u.hashed_password = hash_password('a-new-strong-password')
u.must_change_password = True
db.commit()
print('reset')
"
```

## TLS

Replace the self-signed certificate with a CA-signed one:

```bash
cp fullchain.pem nginx/certs/csap.crt
cp privkey.pem  nginx/certs/csap.key

# nginx runs as uid 101 inside the container and must own the key to read it
docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs

docker compose restart nginx
```

Skipping the `chown` leaves nginx unable to read the key, and the container restart-loops with
`cannot load certificate key ... Permission denied` in `docker compose logs nginx`.

nginx terminates TLS (1.2/1.3 only) and sets HSTS, `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`.
`/login` is rate-limited to 10 requests per minute per source IP.

## Storage and retention

| Data | Location | Grows with |
|---|---|---|
| Users, systems, jobs, snapshots, inventory, changes, audit | `postgres_data` volume | Discovery frequency and device size |
| Uploaded workbooks | `csap_data` volume, `/data/uploads` | Uploads |
| Generated reports | `csap_data` volume, `/data/reports` | Validations, deployments, drift runs |

Snapshots are the largest consumer. Delete old ones from the API when you no longer need them
as a drift baseline:

```bash
curl -k -X DELETE https://localhost/api/v1/snapshots/<id> -H "Authorization: Bearer $TOKEN"
```

Deleting a snapshot cascades to its inventory items. Deleting a system cascades to everything
belonging to it.

Check volume sizes:

```bash
docker system df -v | grep csap
```

## Monitoring

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health/live` | Process is up. No auth, no database. Use for load balancers. |
| `GET /api/v1/health/ready` | Database reachable. Use for readiness checks. |

The backend container has a Docker healthcheck wired to `/health/live`.

## Security notes

- Device credentials are encrypted with Fernet before they touch the database and are never returned by any API response.
- Passwords are hashed with bcrypt.
- All containers run as unprivileged users (`csap` uid 10001, `csapui` uid 10002, nginx unprivileged).
- Uploaded filenames are sanitised and stored under a generated UUID; report paths are checked to prevent traversal.
- The generic exception handler returns a plain `500` and logs the detail server-side, so stack traces and connection strings never reach the client.
- Failed logins are recorded in the audit log with the source IP.

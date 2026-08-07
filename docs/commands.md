---
title: Command reference
nav_order: 6
---

# Command reference
{: .no_toc }

Everything you can type, in one place. Run these from your installation
directory unless stated otherwise.
{: .fs-5 .fw-300 }

1. TOC
{:toc}

---

## Daily operations

```bash
cd ~/csap

docker compose ps                 # what is running and is it healthy
docker compose logs -f            # follow everything
docker compose logs -f backend    # follow one service
docker compose restart worker     # restart one service
docker compose down               # stop, keep all data
docker compose up -d              # start again
```

`make help` lists the same operations as Make targets.

---

## Status checking

Start here whenever something looks wrong.

```bash
# 1. Are all six services up and is the backend healthy?
docker compose ps

# 2. What version is actually running?
curl -k https://localhost/api/v1/health/live
# {"status":"ok","version":"0.8.0"}

# 3. Can the backend reach the database?
curl -k https://localhost/api/v1/health/ready
# {"status":"ready","version":"0.8.0"}

# 4. What image tags are in use?
docker compose images | grep csap

# 5. What does .env think the version is?
grep CSAP_VERSION .env
```

{: .important }
> Checks 2 and 5 must agree. If `.env` pins an older version, `docker compose
> pull` keeps fetching that version and any fix you were told about will not be
> present.

Resource usage and disk:

```bash
docker stats --no-stream
docker system df -v | grep csap
df -h
```

---

## Health endpoints

| Endpoint | Auth | Answers |
|---|---|---|
| `GET /api/v1/health/live` | no | Is the process up? Reports the version. |
| `GET /api/v1/health/ready` | no | Can it reach the database? |

Use `/live` for a load balancer and `/ready` for readiness.

---

## Driving it from the shell

```bash
# Read the admin credentials
grep -E 'CSAP_ADMIN_(EMAIL|PASSWORD)' .env

# Get a token
ADMIN_PASS=$(grep '^CSAP_ADMIN_PASSWORD=' .env | cut -d= -f2-)
TOKEN=$(curl -ks -X POST https://localhost/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@example.com\",\"password\":\"$ADMIN_PASS\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# Use it
curl -ks https://localhost/api/v1/connections -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -ks https://localhost/api/v1/plugins     -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -ks https://localhost/api/v1/snapshots   -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -ks https://localhost/api/v1/audit       -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Confirm auth is enforced
curl -ks -o /dev/null -w 'no token : %{http_code}\n' https://localhost/api/v1/connections
curl -ks -o /dev/null -w 'bad token: %{http_code}\n' https://localhost/api/v1/connections \
  -H 'Authorization: Bearer garbage'
# expect 403 then 401
```

Full endpoint list: [API reference]({{ site.baseurl }}/api-reference).

---

## Backup and restore

```bash
./scripts/backup.sh                 # into ./backups
./scripts/backup.sh /mnt/nfs/csap   # somewhere else
ls -la backups/
```

Each run produces a database dump, an archive of reports and uploads, and a
copy of `.env`. Anything older than 30 days in the target directory is pruned.

Nightly:

```bash
(crontab -l 2>/dev/null; echo "15 2 * * * cd $HOME/csap && ./scripts/backup.sh") | crontab -
```

Restore — destructive, and it asks you to type `restore`:

```bash
./scripts/restore.sh backups/csap-db-<stamp>.sql.gz backups/csap-data-<stamp>.tar.gz
```

---

## Upgrading

```bash
cd ~/csap
git pull                      # REQUIRED FIRST
./scripts/upgrade.sh          # moves to the version in VERSION
./scripts/upgrade.sh 0.7.0    # or a specific version

curl -k https://localhost/api/v1/health/live   # confirm it changed
```

{: .warning }
> **`git pull` before `upgrade.sh`, every time.** `.env` pins `CSAP_VERSION` and
> git never rewrites it. `docker compose pull` on its own re-fetches the version
> you already have.

---

## TLS certificates

```bash
cp fullchain.pem nginx/certs/csap.crt
cp privkey.pem  nginx/certs/csap.key

# nginx runs as uid 101 inside the container and must own the key to read it
docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs

docker compose restart nginx
```

Skip the `chown` and nginx cannot read its key, exits, and restart-loops.

---

## Users and passwords

```bash
# What are the admin credentials?
grep -E 'CSAP_ADMIN_(EMAIL|PASSWORD)' .env
```

Reset a forgotten password:

```bash
docker compose exec backend python -c "
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User
db = SessionLocal()
u = db.query(User).filter(User.email=='admin@example.com').first()
u.hashed_password = hash_password('ChangeMeNow123!')
u.must_change_password = True
db.commit()
print('reset for', u.email)
"
```

---

## Database access

```bash
docker compose exec postgres psql -U csap -d csap

# then, at the psql prompt:
\dt                                        -- tables
SELECT name, host, last_status FROM connections;
SELECT label, object_count, created_at FROM snapshots ORDER BY created_at DESC LIMIT 10;
SELECT filename, status, error_count FROM change_requests ORDER BY created_at DESC LIMIT 10;
SELECT created_at, actor, action, outcome FROM audit_logs ORDER BY created_at DESC LIMIT 20;
```

---

## Running the tests

```bash
docker compose run --rm --entrypoint sh backend -c "pip install -q pytest && pytest -q"
docker compose run --rm --entrypoint sh backend -c "pip install -q ruff  && ruff check app"
```

Neither needs a firewall — they cover validation, planning, dry run, crypto,
JWTs and path traversal.

---

## Removing it

```bash
./scripts/uninstall.sh           # stop, keep all data
./scripts/uninstall.sh --purge   # delete everything, after a final backup
```

---

## Troubleshooting

### Installation

| Symptom | Cause and fix |
|---|---|
| `Package 'docker-ce' has no installation candidate` | Docker's repository was not added. Run the whole Docker block in [Installation]({{ site.baseurl }}/installation), including the two `tee` lines. |
| `Unable to locate package docker-compose-plugin` | Same cause. |
| `docker compose version` not found | You have Compose v1. Install `docker-compose-plugin` from Docker's repo. |
| `permission denied` on `/var/run/docker.sock` | `newgrp docker`, or log out and back in. |
| `python3 is required by the installer` | `sudo apt-get install -y python3`. |

### Startup

| Symptom | Cause and fix |
|---|---|
| nginx stuck `Restarting`, nothing on 443 | `docker compose logs nginx`. If it says `cannot load certificate key ... Permission denied`, run the `chown` in [TLS certificates](#tls-certificates). |
| `PostgreSQL rejected the credentials in DATABASE_URL` | The database volume was created with a different `POSTGRES_PASSWORD` — usually a second checkout on the same host. Run from the directory whose `.env` created it, or `docker compose down -v` to start clean (**destroys data**). |
| `database was unreachable after 30 attempts` | Postgres did not start. `docker compose logs postgres`. |
| Backend restarting | `docker compose logs backend` — nearly always a missing or blank value in `.env`. |
| Port 443 already in use | Set `HTTP_PORT` and `HTTPS_PORT` in `.env`, then `docker compose up -d`. |

### Using it

| Symptom | Cause and fix |
|---|---|
| A fix you were told about is missing | `.env` pins the old version. `git pull && ./scripts/upgrade.sh`, then check `/health/live`. |
| Connection test fails on the certificate | Untick **Verify TLS certificate** for a lab FMC. |
| Connection test returns 401 | The account lacks REST API access, or the API is disabled under System → Configuration → REST API Preferences. |
| Discovery stalls | `docker compose logs -f worker`. Usually the FMC is unreachable or rate-limiting. Large estates legitimately take minutes. |
| "Run a discovery first" on upload | Every workbook is validated against a snapshot. Discover first. |
| Upload rejected | Must be `.xlsx` or `.xlsm`, under 25 MB. |
| "The device configuration changed after this workbook was exported" | Someone changed the FMC after your export. Re-download **Current config** and re-apply your edits. This is the guard working. |
| Validation says 0 changes | Rows are ignored unless `action` is set. See [Workbook reference]({{ site.baseurl }}/workbook-reference). |
| `Provide at least one destination for Connection Events` | Logging enabled without a destination. Set `send_events_to_fmc` to `true`. |
| Rules created but traffic unchanged | You pushed to the FMC but did not deploy. Use **Push & Deploy to FTD**. |

### Verify FMC connectivity yourself

```bash
# Reachable at all?
curl -k -sS -o /dev/null -w 'FMC responds: HTTP %{http_code}\n' https://<fmc-ip>/

# Do the credentials work? This is the exact call CSAP makes.
curl -k -sS -X POST https://<fmc-ip>/api/fmc_platform/v1/auth/generatetoken \
  -u 'apiuser:password' -D - -o /dev/null | grep -i 'x-auth-access-token'

# From inside the container, which is the real path
docker compose exec backend python -c \
  "import httpx; print(httpx.get('https://<fmc-ip>/', verify=False, timeout=10).status_code)"
```

### Support bundle

```bash
cd ~/csap
docker compose logs --no-color > csap-logs.txt
docker compose ps >> csap-logs.txt
curl -k https://localhost/api/v1/health/live >> csap-logs.txt
```

{: .warning }
> Never send your `.env` file. It contains your passwords and encryption keys.

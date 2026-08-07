---
title: Test plan
nav_order: 13
---

# Testing on an Ubuntu server

A complete end-to-end test, from a blank Ubuntu box to a verified deployment.
Steps 1–6 need no FMC at all; step 7 onwards needs one.

---

## 0. Get a test server

Any Ubuntu 22.04/24.04 host works — bare metal, VM, EC2, or Multipass:

```bash
multipass launch 24.04 --name csap --cpus 4 --memory 8G --disk 60G
multipass shell csap
```

---

## 1. Install prerequisites

> **Run this whole block in order.** `docker-ce` and `docker-compose-plugin` are not in Ubuntu's
> default repositories — they come from Docker's own repo, which the middle lines add. Skipping
> ahead to the install line gives you
> `Package 'docker-ce' has no installation candidate` and `Unable to locate package docker-compose-plugin`.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git make openssl python3

# Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Docker's repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Only now do the packages exist
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER && newgrp docker
```

**Check:**

```bash
docker --version           # 27.x or newer
docker compose version     # must report v2.x -- CSAP needs Compose v2
docker run --rm hello-world
```

CSAP needs **Compose v2** (`docker compose`, a space). The old `docker-compose` v1 script in
Ubuntu's universe repo will not work.

If the repository line produces a codename Docker does not publish (anything other than a real
Ubuntu codename such as `jammy` or `noble`), you are on a derivative distribution — substitute the
upstream Ubuntu codename by hand. Check with `. /etc/os-release && echo "$ID $VERSION_ID $VERSION_CODENAME"`.

---

## 2. Get the code and start the stack

```bash
git clone https://github.com/ranilf2005/csap.git
cd csap
./scripts/install.sh --build
```

`--build` builds locally, which also proves the Dockerfiles work on your machine.
Drop it once the GHCR images are published and public.

Expect a few minutes for the first build. The script ends with:

```
[csap] Cisco Security Automation Platform 0.3.1 is running.
  URL:   https://localhost
  Login: admin@example.com
  Password: <generated>
```

**Check:**

```bash
docker compose ps
# postgres, redis, backend, worker, frontend, nginx  -- all Up, backend healthy

curl -k https://localhost/api/v1/health/ready
# {"status":"ready","version":"0.3.1"}
```

If a container is restarting: `docker compose logs <service>`.

---

## 3. Test the API without a browser

```bash
TOKEN=$(curl -ks -X POST https://localhost/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<the generated password>"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "${TOKEN:0:20}..."

curl -ks https://localhost/api/v1/plugins -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Expect:** the `secure_firewall` plugin, its supported engines and entity types.

**Check auth is actually enforced:**

```bash
curl -ks -o /dev/null -w '%{http_code}\n' https://localhost/api/v1/connections
# 403  -- no token

curl -ks -o /dev/null -w '%{http_code}\n' https://localhost/api/v1/connections \
  -H 'Authorization: Bearer garbage'
# 401  -- bad token
```

---

## 4. Test the web UI

From your workstation, browse to `https://<server-ip>`.
Accept the self-signed certificate warning (expected until you install a real cert).

Walk through:
1. Sign in → the "installation password" banner appears
2. User menu → **Change password** → set a new one → sign out and back in
3. **Systems**, **Changes**, **Drift**, **Reports**, **Audit** all load
4. **Audit** already shows your `auth.login` and `auth.change_password` events

---

## 5. Run the automated test suite

```bash
docker compose run --rm --entrypoint sh backend -c "pip install -q pytest && pytest -q"
```

**Expect:** all tests pass. This covers the validation engine, workbook parsing,
change planning, dry-run behaviour, credential encryption, JWT handling and path-traversal defence —
none of which need an FMC.

Lint:

```bash
docker compose run --rm --entrypoint sh backend -c "pip install -q ruff && ruff check app"
```

---

## 6. Prove failure handling without an FMC

Register a system that cannot work, and confirm CSAP fails cleanly rather than hanging:

1. **Systems → Add** — name `FAKE-FMC`, host `192.0.2.1` (reserved, unroutable), any credentials
2. Click **Test**

**Expect:** a red inline message such as `ConnectError: ...` after the timeout, the status badge
turns `error`, and the reason is stored. Nothing crashes. The attempt appears in **Audit**
with outcome `failure`.

---

## 7. Connect a real FMC

You need an FMC (hardware, FMCv, or a dCloud/DevNet sandbox) reachable from the server,
and an account with REST API access.

1. **Systems → Add a managed system**
   - Host: your FMC address
   - Username / password: the API account
   - **Uncheck "Verify TLS certificate"** if the FMC uses a self-signed cert
2. **Test** → expect `Connected to FMC 7.x.x`
3. **Discover** → watch the progress page

**Expect:** the job reaches 100% and reports the object counts. Large FMCs take several minutes
because requests are throttled to stay inside the FMC's ~120/minute limit.

Verify from the shell too:

```bash
docker compose logs -f worker
```

---

## 8. Full change lifecycle

1. **Dashboard → Template** on your new snapshot — downloads `<system>_changes.xlsx`
2. Open it. On the **Hosts** sheet add one row:

   | action | name | value | description |
   |---|---|---|---|
   | create | CSAP-TEST-01 | 10.99.99.1 | CSAP test object |

3. Save, then **Changes → Upload and validate**

**Expect:** status `planned`, 0 errors, 1 planned change.

4. Deliberately break it to prove validation works. Add a second row with a bad address
   (`value` = `not-an-ip`) and a duplicate name, upload again.

**Expect:** status `invalid`, errors naming the row number, and the deploy panel is hidden.

5. Go back to the good workbook, then **Deploy → Dry run → Run**

**Expect:** job succeeds, report opens, shows one `planned` operation, **nothing changed on the FMC**.
Confirm in the FMC UI that `CSAP-TEST-01` does *not* exist.

6. **Deploy → Apply → Run**, confirm the dialog

**Expect:** job succeeds, report shows one `created` operation. The object now exists in the FMC
under Objects → Network → Hosts.

7. **Roll back**

**Expect:** the object is deleted from the FMC and the change status becomes `rolled_back`.

---

## 9. Drift detection

1. Run **Discover** again → second snapshot
2. Change something directly in the FMC (add a host, edit a description)
3. Run **Discover** a third time
4. **Drift** → baseline = snapshot 2, current = snapshot 3 → **Compare**

**Expect:** the report lists exactly what you changed under Added/Removed/Modified,
with before and after values.

---

## 10. Backup, restore and upgrade

```bash
./scripts/backup.sh
ls -la backups/
# csap-db-<stamp>.sql.gz, csap-data-<stamp>.tar.gz, csap-env-<stamp>.bak
```

Test the restore path (destructive — it overwrites the current database):

```bash
./scripts/restore.sh backups/csap-db-<stamp>.sql.gz
# type 'restore' to confirm
```

**Expect:** services restart and your systems, snapshots and reports are all still there.

Upgrade:

```bash
./scripts/upgrade.sh          # backs up first, pulls, recreates, health-checks
```

---

## 11. Reboot resilience

```bash
sudo reboot
```

After the server comes back:

```bash
docker compose ps
curl -k https://localhost/api/v1/health/ready
```

**Expect:** everything restarts automatically (`restart: unless-stopped`) and your data is intact.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `Package 'docker-ce' has no installation candidate` | Docker's repository was not added. Re-run all of step 1 in order, including the two `tee` lines. |
| `Unable to locate package docker-compose-plugin` | Same cause as above. |
| `docker compose version` says `command not found` | You have Compose v1 (`docker-compose`). Install `docker-compose-plugin` from Docker's repo. |
| nginx stuck `Restarting`, `curl` to 443 refused | `docker compose logs nginx`. If it says `cannot load certificate key ... Permission denied`, run `docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs` then `docker compose restart nginx`. |
| `permission denied` on the Docker socket | `newgrp docker`, or log out and back in |
| Port 443 already in use | Set `HTTP_PORT`/`HTTPS_PORT` in `.env`, then `docker compose up -d` |
| Backend restarting | `docker compose logs backend` — usually a missing value in `.env` |
| `bootstrap failed` | Postgres not ready or `DATABASE_URL` wrong; `docker compose logs postgres` |
| Discovery hangs at 5% | FMC unreachable or throttling; `docker compose logs -f worker` |
| TLS errors against the FMC | Uncheck "Verify TLS certificate" for lab devices |
| Browser warns about the certificate | Expected with the self-signed cert; install a real one |
| Upload rejected | Must be `.xlsx`/`.xlsm` and under 25 MB |
| "Run a discovery first" | Every upload validates against a snapshot; discover before uploading |

Collect everything for a support case:

```bash
docker compose logs --no-color > csap-logs.txt
docker compose ps >> csap-logs.txt
docker compose exec backend python -c "from app.core.config import settings; print(settings.csap_version)" >> csap-logs.txt
```

Never send `.env` — it contains your secrets.

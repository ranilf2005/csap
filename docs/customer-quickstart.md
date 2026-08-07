# CSAP quick start

Everything you need to install the Cisco Security Automation Platform on your own Ubuntu
server and run a safe end-to-end test against your Secure Firewall Management Center.

Set aside about 45 minutes. Nothing in this guide changes your firewall until
[step 8](#step-8--apply-the-change), and every step tells you what you should see.

---

## Before you start

**Server** — a dedicated Ubuntu 22.04 or 24.04 host (VM is fine):

| | Minimum | Recommended |
|---|---|---|
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB | 100 GB |

**Network access from that server**
- Outbound HTTPS to `github.com` and `ghcr.io` (to download the software)
- Outbound HTTPS to your FMC management address
- Inbound TCP 443 from wherever your administrators sit

**Credentials** — an FMC account with REST API access.
Read-only is enough for steps 1–7. You only need write permission for step 8.

> **Tip:** create a dedicated `csap-automation` account on the FMC rather than reusing a
> personal login. Every action CSAP takes will be attributable to it in the FMC audit log.

---

## Step 1 — Install Docker

CSAP ships as Docker containers. Run this whole block in order — `docker-ce` is not in
Ubuntu's default repositories, so the middle lines add Docker's own repository first.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git openssl python3

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER && newgrp docker
```

**You should see** all three of these succeed:

```bash
docker --version           # Docker version 27.x or newer
docker compose version     # Docker Compose version v2.x
docker run --rm hello-world
```

If `docker compose version` reports v1, or the command is not found, stop here — CSAP
requires Compose v2.

---

## Step 2 — Install CSAP

```bash
git clone https://github.com/ranilf2005/csap.git
cd csap
./scripts/install.sh --hostname csap.example.com
```

Replace `csap.example.com` with the DNS name or IP your administrators will use.

The installer generates all passwords and encryption keys for you, creates a temporary
self-signed TLS certificate, downloads the software, starts it and checks it is healthy.

**You should see** something like:

```
[csap] Cisco Security Automation Platform 0.3.0 is running.
  URL:   https://csap.example.com
  Login: admin@example.com
  Password: 7Kd2mQx9RtLpVn4wHsYb
```

**Save that password now.** It is also in the `.env` file if you need it again:

```bash
grep CSAP_ADMIN_PASSWORD .env
```

Confirm all six services are running:

```bash
docker compose ps
# postgres, redis, backend, worker, frontend, nginx -- all "Up"

curl -k https://localhost/api/v1/health/ready
# {"status":"ready","version":"0.3.0"}
```

---

## Step 3 — Sign in and secure the account

Open `https://csap.example.com` in a browser.

Your browser will warn about the certificate. That is expected — the installer created a
self-signed one. Accept it for testing; see [Using your own certificate](#using-your-own-certificate)
before going live.

1. Sign in with `admin@example.com` and the generated password
2. A banner warns you are still using the installation password
3. Open the user menu (top right) → **Change password** → set your own (12+ characters)

---

## Step 4 — Connect your firewall

**Systems → Add a managed system**

| Field | What to enter |
|---|---|
| Display name | A label you will recognise, e.g. `DC1-FMC` |
| Product | Cisco Secure Firewall (FMC) |
| Hostname / IP | Your FMC management address |
| Port | 443 |
| Username / Password | Your FMC API account |
| Verify TLS certificate | Untick **only** if your FMC uses a self-signed certificate |

Save, then click **Test**.

**You should see** a green message: `Connected to FMC 7.4.1` (your version will differ),
and the status badge turns green.

If it fails, the message tells you why — wrong credentials, unreachable host, or a
certificate that cannot be verified.

---

## Step 5 — Discover your configuration

Click **Discover** on the system you just added.

CSAP reads your objects, groups, ports, devices, access policies, rules and NAT policies.
It deliberately paces its requests to stay within the FMC's API rate limit, so a large
deployment can take several minutes. The progress bar tells you what it is reading.

**You should see** the job reach 100% with a summary table of how many of each object type
were found. This is called a **snapshot** — an exact record of your configuration at this moment.

Click **View inventory** to browse it, filter by type and search by name.

> Nothing has been changed. Discovery is read-only.

---

## Step 6 — Get your change template

From the **Dashboard**, find your snapshot and click **Template**.

This downloads an Excel workbook built specifically for *your* firewall — it only contains
sheets for object types you actually use.

Open it. Each sheet has an `action` column. **Rows with a blank `action` are ignored**, so
the file is safe to leave partially filled in.

For this test, go to the **Hosts** sheet and add one row:

| action | name | value | description |
|---|---|---|---|
| create | CSAP-TEST-01 | 10.99.99.1 | Temporary test object |

Use an IP address that is not in use. Save the file.

Full column rules for every sheet are in the [workbook reference](workbook-reference.md).

---

## Step 7 — Upload, validate and dry run

**Changes → Upload a change workbook** → pick your system and the file → **Upload and validate**.

**You should see** status `planned`, **0 errors**, **1 planned change**, and a change plan
showing one green `create` for `CSAP-TEST-01`.

### Prove the safety net works

Before deploying, confirm CSAP catches mistakes. Add a second row to the Hosts sheet with a
deliberately invalid address:

| action | name | value |
|---|---|---|
| create | CSAP-TEST-02 | not-an-ip |

Upload it again.

**You should see** status `invalid`, an error naming the exact row and column, and the deploy
panel is hidden. **Errors block deployment** — you cannot push a broken change.

Now re-upload your original, correct file.

### Dry run

In the **Deploy** panel, leave the mode as **Dry run** and click **Run**.

**You should see** the job succeed and a report open listing one `planned` operation.

**Verify in the FMC UI that `CSAP-TEST-01` does *not* exist.** A dry run contacts nothing and
changes nothing — it just shows you exactly what would happen.

---

## Step 8 — Apply the change

> This is the first step that writes to your firewall.

In the **Deploy** panel, switch the mode to **Apply** and click **Run**. You will be asked to
confirm a dialog naming the system and the number of operations.

**You should see** the job succeed and a report showing one `created` operation.

**Verify in the FMC UI:** Objects → Object Management → Network → `CSAP-TEST-01` now exists.

### Roll it back

Return to the change and click **Roll back**, then confirm.

**You should see** the change status become `rolled_back`, and `CSAP-TEST-01` disappear from
the FMC. Rollback reverses every applied operation in reverse order — created objects are
deleted, edited objects are restored to their previous values, deleted objects are recreated.

---

## Step 9 — Detect drift

This proves CSAP can tell you when someone changes the firewall outside your process.

1. Click **Discover** again to take a second snapshot
2. In the **FMC UI directly**, make a small change — add a host object, or edit a description
3. Click **Discover** a third time
4. Go to **Drift**, pick the second snapshot as *baseline* and the third as *current*, click **Compare**

**You should see** a report listing exactly what you changed under Added, Removed or Modified,
with before and after values.

---

## Step 10 — Reports and audit

**Reports** holds every report CSAP has produced — inventory, validation, dry run, deployment
and drift. They are self-contained HTML files, so you can email them, archive them for change
records, or print them to PDF. **View** opens one; **Download** saves it.

**Audit** shows who did what, when, and from which IP — including failed sign-in attempts.

---

## Day-two operations

### Back up

```bash
cd ~/csap
./scripts/backup.sh
ls -la backups/
```

Produces a database dump, an archive of your reports and workbooks, and a copy of your
configuration. Schedule it nightly:

```bash
(crontab -l 2>/dev/null; echo "15 2 * * * cd $HOME/csap && ./scripts/backup.sh") | crontab -
```

### Upgrade

```bash
./scripts/upgrade.sh
```

Backs up first, downloads the new version, restarts and health-checks. If the health check
fails it tells you how to go back.

### Stop, start, remove

```bash
docker compose down          # stop, keep all data
docker compose up -d         # start again
./scripts/uninstall.sh       # stop and remove containers, keep data
./scripts/uninstall.sh --purge   # remove everything (takes a final backup first)
```

### Using your own certificate

```bash
cd ~/csap
cp fullchain.pem nginx/certs/csap.crt
cp privkey.pem  nginx/certs/csap.key
docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs
docker compose restart nginx
```

The `chown` matters — nginx runs as an unprivileged user inside its container and must own
the key file to read it.

---

## If something goes wrong

Start here:

```bash
docker compose ps            # which service is unhealthy?
docker compose logs <name>   # e.g. docker compose logs nginx
```

| Symptom | Cause and fix |
|---|---|
| `Package 'docker-ce' has no installation candidate` | Docker's repository was not added. Re-run all of step 1 in order. |
| `permission denied` talking to Docker | Run `newgrp docker`, or log out and back in |
| Browser cannot connect on 443 | `docker compose ps` — if nginx says `Restarting`, check `docker compose logs nginx` |
| nginx: `cannot load certificate key ... Permission denied` | `docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs` then `docker compose restart nginx` |
| Port 443 already in use | Set `HTTPS_PORT=8443` in `.env`, then `docker compose up -d` |
| Connection test to FMC fails on the certificate | Untick **Verify TLS certificate** for lab firewalls |
| Discovery stalls | `docker compose logs -f worker` — usually the FMC is unreachable or rate-limiting |
| "Run a discovery first" when uploading | Every workbook is validated against a snapshot; discover before uploading |
| Upload rejected | Must be `.xlsx` or `.xlsm` and under 25 MB |

### Sending a support bundle

```bash
cd ~/csap
docker compose logs --no-color > csap-logs.txt
docker compose ps >> csap-logs.txt
```

Send `csap-logs.txt`. **Never send your `.env` file** — it contains your passwords and
encryption keys.

---

## What to remember

- **Dry run is free and always available.** Use it before every apply.
- **Discovery and snapshots are read-only.** Take them as often as you like.
- **Errors block deployment; warnings do not.** Read the warnings anyway.
- **Re-discover after every change** so your baseline stays accurate and drift reports stay meaningful.
- **Back up `.env`.** If you lose `CREDENTIAL_ENCRYPTION_KEY`, every stored device password
  becomes unrecoverable and you will have to re-enter them.

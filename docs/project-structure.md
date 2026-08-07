---
title: Project structure
nav_order: 8
---

# Project structure
{: .no_toc }

Every file in the repository and why it exists.
{: .fs-5 .fw-300 }

1. TOC
{:toc}

---

## Repository root

| File | Purpose |
|---|---|
| `docker-compose.yml` | The whole stack: six services, volumes, health checks. Pins the Compose project name to `csap` — **one checkout per host**. |
| `docker-compose.dev.yml` | Development overlay: live reload, source bind-mounts, ports exposed directly. |
| `.env.example` | Every setting with commentary. Copied to `.env` by the installer, which fills in the secrets. |
| `VERSION` | Single source of truth for the release. `upgrade.sh` reads it to decide what to move to. |
| `Makefile` | Shortcuts for the commands you run daily. `make help` lists them. |
| `LICENSE` | Apache-2.0. |
| `NOTICE` | The prototype disclaimer: no warranty, no affiliation, no liability. |
| `.gitattributes` | Forces LF on shell scripts. Without it, Windows checkouts produce `bad interpreter: /bin/bash^M` on Linux. |
| `.gitignore` | Keeps `.env`, TLS keys, backups and virtualenvs out of git. |

## `backend/` — the API and the engine

### Core

| File | Purpose |
|---|---|
| `app/core/config.py` | Typed settings from the environment. Rejects blank secrets at startup rather than failing later. |
| `app/core/database.py` | SQLAlchemy engine and session factory. |
| `app/core/security.py` | bcrypt hashing, JWT creation and validation. |
| `app/core/crypto.py` | Fernet encryption for device credentials. |
| `app/core/logging.py` | Log formatting and level. |

### Data model

| File | Purpose |
|---|---|
| `app/models/base.py` | Declarative base, UUID primary keys, timestamp mixin. |
| `app/models/user.py` | Accounts. |
| `app/models/connection.py` | Managed systems and their encrypted credentials. |
| `app/models/snapshot.py` | Snapshots and inventory items. |
| `app/models/change.py` | Change requests: rows, validation, plan, deployment. |
| `app/models/job.py` | Background work with status and progress. |
| `app/models/report.py` | Generated HTML artifacts. |
| `app/models/audit.py` | Append-only action log. |

### API

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app, lifespan, generic error handler. |
| `app/schemas.py` | Pydantic request and response models — the API contract. |
| `app/api/deps.py` | Auth dependency, database session, audit helper. |
| `app/api/v1/auth.py` | Login, current user, password change. |
| `app/api/v1/connections.py` | Register, update, delete and test managed systems. |
| `app/api/v1/discovery.py` | Queue discovery, poll jobs. |
| `app/api/v1/inventory.py` | Snapshots, paged inventory, Excel export, inventory report. |
| `app/api/v1/changes.py` | Upload, validate, plan, deploy, roll back, findings, IaC artifacts, deployment targets. |
| `app/api/v1/reports.py` | List, view, download, delete reports. |
| `app/api/v1/drift.py` | Compare two snapshots. |
| `app/api/v1/audit.py` | Query the audit trail. |
| `app/api/v1/health.py` | Liveness and readiness. |
| `app/api/v1/plugins.py` | Which products are available. |

### Plugins

| File | Purpose |
|---|---|
| `app/plugins/base.py` | **The contract.** Every product implements `SecurityPlugin`. Also the shared types: `ChangePlan`, `ValidationIssue`, `DiscoveryResult`. |
| `app/plugins/registry.py` | Finds and instantiates plugins at startup. Cached. |
| `app/plugins/secure_firewall/plugin.py` | The FMC plugin: discover, validate, plan, deploy, roll back, deploy to devices. |
| `app/plugins/secure_firewall/fmc_client.py` | FMC REST client: token refresh, domains, pagination, rate limiting, retries. |
| `app/plugins/secure_firewall/engines.py` | Renders a plan as Ansible or Terraform. |

### Services

| File | Purpose |
|---|---|
| `app/services/discovery.py` | Runs a plugin's discovery and writes the snapshot. |
| `app/services/changes.py` | The change lifecycle: parse, validate, plan, deploy, roll back. |
| `app/services/workbook.py` | Reads uploaded workbooks; reads the provenance markers. |
| `app/services/templates.py` | Builds the Excel exports and the findings workbook. |
| `app/services/reports.py` | Renders and stores HTML reports. |
| `app/services/drift.py` | Compares two snapshots. |
| `app/services/connections.py` | Decrypts credentials into a plugin context. |
| `app/services/storage.py` | Path handling for uploads and reports, with traversal defence. |

### Workers and reports

| File | Purpose |
|---|---|
| `app/workers/celery_app.py` | Celery configuration. |
| `app/workers/tasks.py` | The queued tasks: discover, deploy, roll back. |
| `app/report_templates/*.html` | Self-contained HTML reports — no external CSS or JS, so they work offline. |
| `app/bootstrap.py` | Waits for Postgres, creates the schema, seeds the admin. Distinguishes a rejected password from an unreachable database. |
| `entrypoint.sh` | Chooses API, worker or beat from `CSAP_ROLE`. |

## `frontend/` — the web portal

| File | Purpose |
|---|---|
| `app/main.py` | Server-rendered routes. Holds the session, adds the bearer token, proxies to the backend. |
| `app/templates/base.html` | Layout and navigation. |
| `app/templates/*.html` | One template per screen. |
| `app/templates/partials/` | HTMX fragments for live updates. |
| `app/static/css/app.css` | Styling on top of Bootstrap. |
| `Dockerfile` | Vendors Bootstrap, HTMX and Chart.js at build time so runtime needs no internet. |

## `nginx/`

| File | Purpose |
|---|---|
| `nginx.conf` | Worker settings, gzip, temp paths writable by an unprivileged user, the login rate-limit zone. |
| `conf.d/csap.conf` | TLS termination, security headers, routing, 80→443 redirect. |
| `certs/` | Your certificate. Git-ignored. |

## `scripts/`

| Script | Purpose |
|---|---|
| `install.sh` | Generates secrets, creates a TLS certificate, pulls images, starts, health-checks. Refuses to run against a database it has no credentials for. |
| `upgrade.sh` | Backs up, checks the `.env` matches the running database, moves to the version in `VERSION`, health-checks. |
| `backup.sh` | Database dump, artifact archive, `.env` copy. Prunes after 30 days. |
| `restore.sh` | Restores a backup. Requires typing `restore`. |
| `uninstall.sh` | Stops the stack. `--purge` also deletes data, after a final backup. |

## `.github/workflows/`

| Workflow | Purpose |
|---|---|
| `ci.yml` | Lint, backend tests, **frontend template render tests**, image builds, and a full stack smoke test that logs in over HTTPS. |
| `release.yml` | On a `v*` tag: builds `amd64` and `arm64`, pushes to GHCR, publishes a release bundle. |

## `backend/tests/`

Named for the behaviour they protect, not the function they call.

| Suite | Protects |
|---|---|
| `test_change_engine.py` | Validation, planning, ordering, dry run |
| `test_access_rules.py` | Access rule lifecycle and references |
| `test_rule_logging.py` | The logging-destination rule the FMC enforces |
| `test_ignored_rows.py` | Rows edited without an action are not silently dropped |
| `test_workbook_guardrails.py` | Provenance, dropdowns, README guidance |
| `test_field_guide.py` | Mandatory columns are marked and documented |
| `test_template_export.py` | Export contents and round-trip |
| `test_findings.py` | Every finding carries remediation |
| `test_iac_engines.py` | Generated Ansible and Terraform are valid |
| `test_device_deployment.py` | FMC-to-FTD deployment handshake |
| `test_workbook.py` | Upload parsing |
| `test_crypto.py`, `test_security.py` | Credential encryption, hashing, JWTs |
| `test_storage.py` | Path traversal defence |
| `test_api.py` | Auth is actually enforced |

`frontend/tests/test_templates.py` **renders** every template with realistic
data. Compiling alone missed a bug where Jinja resolved `page.items` to a
dict's built-in method — that class of failure only appears at render time.

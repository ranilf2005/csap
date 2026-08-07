# Cisco Security Automation Platform (CSAP)

> ### ⚠️ Prototype — use at your own risk
>
> This is an **unfinished prototype published for evaluation only**. It is not a product,
> it is not supported, and it carries no warranty. It is **not affiliated with, endorsed by
> or supported by Cisco Systems, Inc.** or any other company.
>
> **This software makes changes to network security devices.** A mistake can remove firewall
> rules or break connectivity. You are solely responsible for what you run it against, for
> taking your own backups, for reviewing every change before applying it, and for the outcome.
> No author, contributor, employer or affiliated organisation accepts any liability.
>
> Test against a **laboratory FMC with a read-only account** first. See [NOTICE](NOTICE) for
> the full disclaimer and [LICENSE](LICENSE) for the Apache-2.0 terms.

Docker-first automation and governance platform for the Cisco security portfolio.
Cisco Secure Firewall (FMC) is the first product plugin; ISE, Umbrella, Duo, XDR,
Secure Access and others plug into the same core without changing it.

**Workflow:** Connect → Discover → Snapshot → Dynamic Excel → Validate → Report → Dry run → Deploy (REST) → Roll back → Drift

Nothing is written to a device until you explicitly choose *Apply* and confirm.

## What it does today

| Capability | Detail |
|---|---|
| Discovery | Objects, groups, ports, URLs, devices, access policies, access rules and NAT policies from FMC, with live progress and throttling |
| Snapshots | Immutable point-in-time inventory, the baseline for validation and drift |
| Dynamic Excel | Workbook generated per snapshot — only the sheets that device actually needs |
| Validation | Schema, address/CIDR/port syntax, duplicates, existence checks, group member resolution, unsafe-delete warnings |
| Change plan | Ordered create/update/delete diff; members before groups, deletes reversed |
| Dry run | Full operation list and report without touching the device |
| Deployment | REST create, update and delete with per-operation results |
| Rollback | Reverts an applied deployment in reverse order using recorded before-state |
| Drift | Compares any two snapshots; ignores volatile FMC bookkeeping fields |
| Reports | Self-contained HTML for inventory, validation, dry run, deployment and drift |
| Audit | Append-only log of every action with user, outcome and source IP |

## Documentation

| Guide | For |
|---|---|
| [**Quick start**](docs/customer-quickstart.md) | **Customers: install and test end to end** |
| [Installation](docs/installation.md) | Standing it up on Ubuntu |
| [Testing on Ubuntu](docs/testing-on-ubuntu.md) | End-to-end test plan, with or without an FMC |
| [Web UI guide](docs/user-guide.md) | Every screen and the daily workflow |
| [Workbook reference](docs/workbook-reference.md) | What goes in each Excel column |
| [Administration](docs/administration.md) | Backup, upgrade, secrets, troubleshooting |
| [API reference](docs/api-reference.md) | Driving CSAP from scripts or CI |
| [Plugin development](docs/plugin-development.md) | Adding another Cisco product |

---

## For customers — install

Requirements: Ubuntu 22.04+ (or any Docker host), 4 vCPU, 8 GB RAM, 100 GB disk, Docker Engine + Compose v2.

```bash
git clone https://github.com/ranilf2005/csap.git
cd csap
./scripts/install.sh
```

The installer generates all secrets and a self-signed TLS certificate, pulls the
published images, starts the stack, waits for health, and prints the admin
password. Then open `https://<server-ip>` and sign in.

Use a real certificate in production by replacing `nginx/certs/csap.crt` and
`nginx/certs/csap.key`, then `docker compose restart nginx`.

| Task | Command |
|---|---|
| Upgrade to the latest release | `./scripts/upgrade.sh` |
| Upgrade to a specific version | `./scripts/upgrade.sh 0.2.0` |
| Back up database + artifacts | `./scripts/backup.sh` |
| Restore | `./scripts/restore.sh backups/csap-db-<stamp>.sql.gz` |
| Stop (keep data) | `./scripts/uninstall.sh` |
| Remove everything | `./scripts/uninstall.sh --purge` |
| View logs | `docker compose logs -f` |

---

## For developers

```bash
cp .env.example .env          # then fill in the secrets, or run install.sh once
make dev                      # live reload: API on :8000, UI on :8080
make test                     # backend tests
make lint                     # ruff
```

`make help` lists every target.

### Architecture

```
                      Customer browser
                            │ HTTPS 443
                    ┌───────▼────────┐
                    │  nginx (TLS)   │
                    └───┬────────┬───┘
              /         │        │  /api/
      ┌───────▼──────┐  │  ┌─────▼──────────┐
      │ frontend     │  │  │ backend        │
      │ Jinja2/HTMX  │──┼─▶│ FastAPI        │
      └──────────────┘  │  └──┬────┬────┬───┘
                        │     │    │    │
                 ┌──────▼──┐  │  ┌─▼──┐ │
                 │ worker  │◀─┴──│redis│ │
                 │ Celery  │     └────┘ │
                 └────┬────┘            │
                      └──────┬──────────┘
                        ┌────▼─────┐   ┌──────────┐
                        │ postgres │   │ /data    │
                        └──────────┘   │ artifacts│
                                       └──────────┘
                              │
                       Cisco FMC / ISE / Umbrella ... (REST)
```

### Repository layout

| Path | Purpose |
|---|---|
| `backend/app/core/` | Config, DB session, JWT, credential encryption, logging |
| `backend/app/models/` | SQLAlchemy tables (users, connections, jobs, snapshots, inventory, changes, reports, audit) |
| `backend/app/api/v1/` | REST endpoints |
| `backend/app/plugins/` | Plugin contract + one package per Cisco product |
| `backend/app/services/` | Discovery, workbook parsing, change lifecycle, drift, reports, storage |
| `backend/app/report_templates/` | Self-contained HTML report templates |
| `backend/app/workers/` | Celery app and tasks |
| `frontend/app/` | Server-rendered UI (Jinja2 + HTMX + Bootstrap 5) |
| `nginx/` | TLS termination, reverse proxy, security headers, login rate limit |
| `scripts/` | install / upgrade / backup / restore / uninstall |
| `docs/` | User, admin, API and plugin guides |
| `.github/workflows/` | CI and GHCR release pipeline |

### Adding a new Cisco product

1. Create `backend/app/plugins/<product>/plugin.py`.
2. Subclass `SecurityPlugin` and set a `PluginManifest`.
3. Implement `test_connection`, `discover`, `template_spec`, `validate`, `plan`, `deploy`.

The registry auto-discovers it at startup; the UI, jobs, snapshots, Excel
generation, reporting and audit trail all work without further changes.

### Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Obtain a JWT |
| `GET` | `/api/v1/plugins` | List available product plugins |
| `POST` | `/api/v1/connections` | Register a managed system |
| `POST` | `/api/v1/connections/{id}/test` | Verify credentials, detect version |
| `POST` | `/api/v1/discovery/{id}` | Queue a discovery job |
| `GET` | `/api/v1/snapshots/{id}/inventory` | Paged inventory |
| `GET` | `/api/v1/snapshots/{id}/template` | Download the dynamic Excel workbook |
| `POST` | `/api/v1/changes` | Upload and validate a workbook |
| `POST` | `/api/v1/changes/{id}/deploy` | Dry run or apply |
| `POST` | `/api/v1/changes/{id}/rollback` | Revert an applied deployment |
| `POST` | `/api/v1/drift` | Compare two snapshots |
| `GET` | `/api/v1/audit` | Audit trail |

Full reference: [docs/api-reference.md](docs/api-reference.md). Interactive docs: `https://<host>/api/docs`.

---

## Releasing

```bash
echo 0.2.0 > VERSION
git commit -am "Release 0.2.0" && git push
make release            # tags v0.2.0 and pushes
```

The `Release` workflow builds `linux/amd64` + `linux/arm64` images, pushes them to
`ghcr.io/ranilf2005/csap-{backend,frontend,nginx}`, and publishes a GitHub Release
containing `csap-<version>.tar.gz` (compose file, `.env.example`, scripts, README).

Make the GHCR packages **public** once so customers can pull without a token:
GitHub → your profile → Packages → each `csap-*` package → Package settings → Change visibility.

## Roadmap

| Version | Scope | Status |
|---|---|---|
| 0.1 | Login, FMC discovery, inventory, dynamic Excel template | done |
| 0.2 | Excel upload, validation engine, HTML reports | done |
| 0.3 | REST deployment with dry run and rollback, drift detection, audit UI | done |
| 0.4 | Ansible and Terraform engines, access-rule and NAT support | next |
| 0.5 | Scheduling, scheduled drift, AI recommendations | planned |
| 0.6+ | Security Cloud Control, ISE, Secure Access, Umbrella, Duo, XDR plugins | planned |
| 1.0 | RBAC, SSO, multi-user, approval workflow, compliance dashboards | planned |

## Security notes

- Device credentials are encrypted at rest with Fernet (`CREDENTIAL_ENCRYPTION_KEY`) and are never returned by the API.
- Passwords are hashed with bcrypt; sessions use short-lived JWTs.
- Uploaded filenames are sanitised and stored under a generated UUID; report paths are checked against directory traversal.
- All containers run as unprivileged users; nginx enforces HSTS, `X-Frame-Options`, `nosniff` and a login rate limit.
- Applying changes to a device requires an explicit confirmation flag; dry run is the default.
- `.env` is created with `0600` permissions and is git-ignored — never commit it.
- Losing `CREDENTIAL_ENCRYPTION_KEY` makes stored device credentials unrecoverable. Back it up.

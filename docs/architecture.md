---
title: Architecture
nav_order: 7
---

# Architecture
{: .no_toc }

1. TOC
{:toc}

---

## Shape of the system

```
                        Administrator's browser
                                 │ HTTPS 443
                    ┌────────────▼─────────────┐
                    │  nginx                   │  TLS, security headers,
                    │  (unprivileged, uid 101) │  login rate limit
                    └────┬────────────────┬────┘
                     /   │                │  /api/
          ┌─────────────▼──┐        ┌─────▼──────────┐
          │ frontend       │  HTTP  │ backend        │
          │ FastAPI        │───────►│ FastAPI        │
          │ Jinja2 + HTMX  │        │ REST + OpenAPI │
          └────────────────┘        └──┬──────┬───┬──┘
                                       │      │   │
                        ┌──────────────▼─┐  ┌─▼───▼────┐
                        │ worker         │  │ redis    │
                        │ Celery         │◄─┤ queue    │
                        └───────┬────────┘  └──────────┘
                                │
                 ┌──────────────▼───────┐   ┌─────────────┐
                 │ postgres             │   │ /data       │
                 │ state and audit      │   │ artifacts   │
                 └──────────────────────┘   └─────────────┘
                                │
                    Cisco Secure Firewall (FMC) over REST
```

Six containers, one `docker compose up`. Everything runs as an unprivileged
user.

### Why the frontend is a separate service

The browser never talks to the backend directly. The frontend holds the session
cookie and adds the bearer token server-side, so **the JWT is never exposed to
JavaScript**. It also means the API can be driven by scripts and CI on exactly
the same endpoints the UI uses — there is no private API.

### Why work happens in a worker

Discovering a large FMC takes minutes, because requests are deliberately paced.
Doing that inside a web request would block a worker thread and time out behind
nginx. Discovery, deployment and rollback are queued as **jobs**; the UI polls
progress every three seconds.

---

## Data model

```
users                                    connections
  id, email, hashed_password               id, name, product
  role, must_change_password               host, port, username
                                           encrypted_password
                                           verify_tls, last_status
                                           detected_version
                                                  │
                            ┌─────────────────────┼──────────────────┐
                            ▼                     ▼                  ▼
                       snapshots             change_requests       jobs
                         id, label             id, filename         id, job_type
                         product_version       status               status, progress
                         object_count          rows      (JSONB)    message
                         summary  (JSONB)      validation(JSONB)    result   (JSONB)
                            │                  plan      (JSONB)    started_at
                            ▼                  deployment(JSONB)    finished_at
                     inventory_items           error/warning counts
                       item_type
                       external_id           reports              audit_logs
                       name                    kind, title          actor, action
                       payload   (JSONB)       stored_path          target_type/id
                                               summary  (JSONB)     outcome, source_ip
```

### The design decisions that matter

**Snapshots are immutable.** Every discovery creates a new one. Nothing ever
updates an old snapshot. That is what makes drift detection possible — you are
always comparing two known points in time, never a moving target.

**Device payloads are stored verbatim as JSONB.** `inventory_items.payload`
holds exactly what the FMC returned. The platform does not impose a schema on
product data, so a plugin for ISE or Umbrella stores its own shapes in the same
table without a migration.

**Change requests carry their whole history.** `rows`, `validation`, `plan` and
`deployment` are kept on the record. Months later you can see what was
uploaded, what was flagged, what was planned, and what actually happened.

**Files are not in the database.** Uploaded workbooks and generated reports live
under `/data`; the row stores a path. Postgres stays small and quick to back up.

**Audit is append-only.** Nothing in the application updates or deletes an audit
row.

### Cascade behaviour

Deleting a connection removes its snapshots, inventory, change requests and
reports. Deleting a snapshot removes its inventory items. A job survives the
connection it referenced (`ON DELETE SET NULL`) so history is not lost.

---

## Caching and performance

There is deliberately **no application cache in front of the database**. Cached
firewall state that is subtly stale is worse than no cache, because it makes
validation wrong. Instead:

| Layer | Approach |
|---|---|
| Device state | Read once per discovery into a snapshot, then reused from Postgres. Validation never calls the FMC. |
| Redis | Celery broker and result backend only. Not used as a data cache. |
| Plugin registry | Loaded once per process with `functools.lru_cache` — no filesystem scan per request. |
| Settings and crypto | `lru_cache` on settings and the Fernet cipher, so the key is derived once. |
| Database | `pool_pre_ping` with a 10-connection pool and 20 overflow; indexes on every foreign key and on the columns actually filtered. |
| Inventory reads | Paged at the query level, never loaded whole. |
| Excel export | Capped at 10,000 rows per sheet, and says so in the workbook. |
| Static assets | Bootstrap, HTMX and Chart.js are baked into the image at build time, so the platform works air-gapped. |
| nginx | gzip on text responses. |

**FMC rate limiting** is the real performance constraint. The FMC allows roughly
120 requests per minute; the client enforces a floor of 0.5 seconds between
calls and retries `429` with exponential backoff. A large estate therefore takes
minutes to discover. That is intentional — the alternative is being throttled or
locked out.

---

## Security

### Credentials

Device passwords are encrypted with **Fernet** (AES-128-CBC with HMAC) before
they touch the database, using `CREDENTIAL_ENCRYPTION_KEY`. They are write-only
through the API — no response ever contains one, and the UI never displays one
after it is saved.

{: .warning }
> Losing `CREDENTIAL_ENCRYPTION_KEY` makes every stored device password
> permanently unrecoverable. Back up `.env`.

### Authentication

Passwords are hashed with **bcrypt**. Sessions are short-lived **JWTs** (60
minutes by default) signed with `SECRET_KEY`, validated for issuer and
expiry. A missing token returns `403`, an invalid one `401`. Login failures are
recorded in the audit log with the source IP, and rate-limited by nginx to ten
attempts per minute per address.

### Making changes

Several deliberate gates before anything reaches a device:

1. **Errors block deployment** outright.
2. **Warnings require explicit acknowledgement.**
3. **A stale workbook is rejected** — the export records which snapshot it came
   from, so you cannot overwrite a change someone else made after your export.
4. **Dry run is the default**, and applying requires `confirm=true`.
5. **The exact API calls are shown** before you approve them.
6. **Pushing to the FMC and deploying to firewalls are separate actions.**

### Platform hardening

- Every container runs as an unprivileged user (`csap` 10001, `csapui` 10002, nginx 101)
- nginx sets HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, and hides its version
- Session cookies are `HttpOnly`, `SameSite=Lax` and `Secure` in production
- Uploaded filenames are sanitised and stored under a generated UUID; report paths are resolved and checked against their base directory to defeat traversal
- Uploads are capped at 25 MB and 20,000 rows per sheet
- The generic exception handler returns a plain `500`; stack traces and connection strings are logged server-side only
- Jinja autoescaping is on for both the UI and generated reports
- `.env` is created `0600` and is git-ignored
- Secrets are generated by the installer, never shipped with defaults

### Known limitations

Be honest with anyone evaluating this:

- **One administrator account.** No RBAC, no SSO, no per-user attribution beyond that login.
- **No approval workflow.** Anyone who can sign in can apply changes.
- **Self-signed TLS by default** until you install a real certificate.
- **`verify_tls` can be disabled per connection** for lab devices, which disables certificate validation to that device.

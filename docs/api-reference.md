---
title: API reference
nav_order: 9
---

# API reference

Base URL: `https://<host>/api/v1`
Interactive docs: `https://<host>/api/docs` · OpenAPI schema: `https://<host>/api/openapi.json`

## Authentication

All endpoints except `/health/*` require a bearer token.

```bash
TOKEN=$(curl -ks -X POST https://csap.example.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"..."}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

Send it as `Authorization: Bearer $TOKEN`. Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60).

Missing token → `403`. Invalid or expired token → `401`.

---

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health/live` | no | Process is alive |
| GET | `/health/ready` | no | Database reachable |

## Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | `{email, password}` → `{access_token, expires_in, must_change_password}` |
| GET | `/auth/me` | Current user |
| POST | `/auth/change-password` | `{current_password, new_password}` → `204` |

## Plugins

| Method | Path | Description |
|---|---|---|
| GET | `/plugins` | Registered product plugins, their engines and entity types |

## Connections

| Method | Path | Description |
|---|---|---|
| GET | `/connections` | List managed systems |
| POST | `/connections` | `{name, product, host, port, username, password, verify_tls}` |
| PATCH | `/connections/{id}` | Partial update; `password` is re-encrypted |
| DELETE | `/connections/{id}` | Cascades to snapshots, changes and reports |
| POST | `/connections/{id}/test` | Authenticate and detect the product version |

Passwords are write-only — no response ever contains them.

## Discovery

| Method | Path | Description |
|---|---|---|
| POST | `/discovery/{connection_id}` | Queue a discovery job → `202` with the job |
| GET | `/discovery/jobs` | Recent jobs (`?limit=`) |
| GET | `/discovery/jobs/{id}` | Poll one job: `status`, `progress`, `message`, `result` |

`409` if a discovery is already running for that system.

## Snapshots and inventory

| Method | Path | Description |
|---|---|---|
| GET | `/snapshots` | `?connection_id=&limit=` |
| GET | `/snapshots/{id}/inventory` | Paged: `?item_type=&search=&limit=&offset=` |
| GET | `/snapshots/{id}/template` | Download the dynamic `.xlsx` |
| POST | `/snapshots/{id}/report` | Generate an HTML inventory report |
| DELETE | `/snapshots/{id}` | Delete a snapshot and its inventory |

## Changes

| Method | Path | Description |
|---|---|---|
| POST | `/changes` | `multipart/form-data`: `connection_id` + `file`. Parses and validates immediately. |
| GET | `/changes` | `?connection_id=&limit=` |
| GET | `/changes/{id}` | Full detail including `validation`, `plan` and `deployment` |
| POST | `/changes/{id}/revalidate` | Re-validate against the newest snapshot |
| POST | `/changes/{id}/deploy` | `{dry_run, engine, confirm}` → `202` with the job |
| POST | `/changes/{id}/rollback` | Revert an applied deployment → `202` |
| DELETE | `/changes/{id}` | Delete the change and its stored workbook |

Deploy guards: `409` if there is no plan or errors remain; `400` if `dry_run=false`
without `confirm=true`.

```bash
# upload
curl -ks -X POST https://csap.example.com/api/v1/changes \
  -H "Authorization: Bearer $TOKEN" \
  -F connection_id=<id> -F file=@changes.xlsx

# dry run
curl -ks -X POST https://csap.example.com/api/v1/changes/<id>/deploy \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run": true, "engine": "rest"}'

# apply
curl -ks -X POST https://csap.example.com/api/v1/changes/<id>/deploy \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run": false, "engine": "rest", "confirm": true}'
```

## Reports

| Method | Path | Description |
|---|---|---|
| GET | `/reports` | `?kind=&connection_id=&subject_id=&limit=` |
| GET | `/reports/{id}/html` | Render inline |
| GET | `/reports/{id}/download` | Download as an attachment |
| DELETE | `/reports/{id}` | Delete the record and the file |

`kind` is one of `inventory`, `validation`, `dry_run`, `deployment`, `drift`.

## Drift

| Method | Path | Description |
|---|---|---|
| POST | `/drift` | `{baseline_snapshot_id, current_snapshot_id}` → counts plus a `report_id` |

Both snapshots must belong to the same system, otherwise `400`.

## Audit

| Method | Path | Description |
|---|---|---|
| GET | `/audit` | `?action=&actor=&limit=&offset=` |

---

## Status codes

| Code | Meaning |
|---|---|
| 200 / 201 / 202 / 204 | Success (202 = job queued) |
| 400 | Bad request — see `detail` |
| 401 | Invalid or expired token |
| 403 | No token supplied |
| 404 | Not found |
| 409 | Conflict — duplicate name, job already running, or unmet precondition |
| 410 | Report file no longer on disk |
| 413 | Upload over 25 MB |
| 500 | Internal error — details are logged server-side only |

## Polling a job

```bash
JOB=$(curl -ks -X POST https://csap.example.com/api/v1/discovery/<conn-id> \
  -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

until [ "$(curl -ks https://csap.example.com/api/v1/discovery/jobs/$JOB \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')" != "running" ]; do
  sleep 5
done
```

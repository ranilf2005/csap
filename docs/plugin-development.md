---
title: Plugin development
nav_order: 10
---

# Plugin development

Adding a Cisco product to CSAP means writing one Python package. The core platform —
authentication, jobs, snapshots, the Excel engine, validation reporting, deployment
orchestration, drift detection, reports and the audit trail — is product-agnostic and
does not change.

## The contract

Every plugin subclasses `SecurityPlugin` in [`app/plugins/base.py`](../backend/app/plugins/base.py):

| Method | Required | Purpose |
|---|---|---|
| `test_connection(ctx)` | yes | Authenticate; return the detected product version |
| `discover(ctx, progress)` | yes | Read the live configuration into a flat item list |
| `template_spec(discovery)` | yes | Sheet → column headers for the dynamic workbook |
| `validate(rows, discovery)` | yes | Check an uploaded workbook against schema and live state |
| `plan(rows, discovery)` | yes | Diff desired vs. discovered state into a `ChangePlan` |
| `deploy(ctx, plan, engine, dry_run, progress)` | yes | Apply the plan through an engine |
| `rollback(ctx, result)` | no | Undo an applied deployment; raises `NotImplementedError` by default |

Plugins are **synchronous**. They run inside a Celery worker, so blocking I/O is fine.

## Skeleton

```
backend/app/plugins/my_product/
├── __init__.py
├── plugin.py          # subclass of SecurityPlugin
└── client.py          # REST/SDK wrapper
```

```python
# backend/app/plugins/my_product/plugin.py
from app.plugins.base import (
    ChangePlan, ConnectionContext, ConnectionResult, DeploymentResult,
    DiscoveryResult, PluginManifest, ProgressCallback, SecurityPlugin,
    ValidationIssue, ValidationResult,
)


class MyProductPlugin(SecurityPlugin):
    manifest = PluginManifest(
        key="my_product",                       # stable identifier stored on every connection
        display_name="Cisco My Product",
        description="What this plugin manages.",
        default_port=443,
        engines=("rest",),                      # add "ansible"/"terraform" when implemented
        entity_types=("policy", "endpoint"),
    )

    def test_connection(self, ctx: ConnectionContext) -> ConnectionResult:
        ...

    def discover(self, ctx, progress: ProgressCallback | None = None) -> DiscoveryResult:
        ...

    def template_spec(self, discovery: DiscoveryResult | None = None) -> dict[str, list[str]]:
        ...

    def validate(self, rows, discovery) -> ValidationResult:
        ...

    def plan(self, rows, discovery) -> ChangePlan:
        ...

    def deploy(self, ctx, plan, engine="rest", dry_run=True, progress=None) -> DeploymentResult:
        ...
```

Registration is automatic: [`registry.py`](../backend/app/plugins/registry.py) walks every
sub-package of `app.plugins`, imports `plugin.py` and instantiates any concrete `SecurityPlugin`.
Restart the backend and it appears in the product dropdown.

## Data shapes

**Discovery items** — one flat dict per object. `payload` is stored verbatim as JSONB:

```python
{"item_type": "host", "external_id": "abc-123", "name": "WEB01", "payload": {...}}
```

`item_type` values become the inventory filter options and the drift comparison keys.

**Template spec** — drives the workbook. Return only the sheets that make sense for what
was actually discovered:

```python
{"Hosts": ["action", "name", "value", "description"]}
```

**Validation issues** — `severity` is `error`, `warning` or `info`. Any `error` blocks deployment.
`row` is the Excel row number (data starts at 2).

**Change plan entries** — free-form dicts, but these keys are used by the UI and reports:

```python
{
  "sheet": "Hosts", "kind": "hosts", "entity": "host",
  "name": "APP01", "action": "create",
  "payload": {...},          # create/update
  "id": "abc-123",           # update/delete
  "before": {...},           # update/delete, enables rollback
}
```

**Deployment details** — include an `undo` record per applied operation to make rollback work:

```python
{"status": "created", "undo": {"action": "delete", "kind": "hosts", "id": "new-id"}}
```

## Rules that matter

1. **`dry_run=True` must not touch the device.** Return the operations with `status: "planned"`.
2. **Order dependencies in `plan()`.** Create members before groups; reverse the delete list.
3. **Report progress.** Call `progress(percent, message)` — it drives the live job page.
4. **Raise typed errors.** Wrap transport failures in your own exception type and let
   `test_connection` return `ConnectionResult(ok=False, detail=...)` rather than raising.
5. **Respect rate limits.** The FMC client throttles to ~2 requests/second; do the same.
6. **Never log credentials.**

## Testing

Plugin logic is pure and testable without a device — see
[`tests/test_change_engine.py`](../backend/tests/test_change_engine.py) for the pattern:
build a `DiscoveryResult` by hand, then assert on `validate`, `plan` and a dry-run `deploy`.

```bash
docker compose run --rm --entrypoint sh backend -c "pip install -q pytest && pytest -q"
```

## Checklist

- [ ] `manifest.key` is stable — it is stored on every connection row
- [ ] `discover()` reports progress and tolerates endpoints the device does not expose
- [ ] `template_spec()` omits sheets for entity types that were not found
- [ ] `validate()` catches duplicates, missing references and malformed values
- [ ] `plan()` orders operations correctly and records `before` state
- [ ] `deploy(dry_run=True)` performs no writes
- [ ] `deploy()` records `undo` data so `rollback()` works
- [ ] Tests cover validate, plan and dry-run without network access

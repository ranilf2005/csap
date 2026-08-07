"""Render every UI template with realistic API-shaped data.

Compiling a template only checks syntax. It will not catch the class of bug where
Jinja resolves `page.items` to a dict's built-in `.items` method instead of the
data, which raises TypeError only at render time.
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "app" / "templates"

env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)

USER = "admin@example.com"
NOW = "2026-08-07T09:15:00+00:00"

CONNECTION = {
    "id": "c1", "name": "LAB-FMC", "product": "secure_firewall", "host": "198.18.1.10",
    "port": 443, "verify_tls": False, "is_active": True, "last_status": "connected",
    "last_error": None, "detected_version": "7.4.1", "created_at": NOW,
}

SNAPSHOT = {
    "id": "s1", "connection_id": "c1", "label": "LAB-FMC 2026-08-07 09:15 UTC",
    "product": "secure_firewall", "product_version": "7.4.1", "object_count": 52,
    "summary": {"host": 2, "network": 11, "port": 29, "access_rule": 5}, "created_at": NOW,
}

JOB = {
    "id": "66a5338b-0000-0000-0000-000000000000", "connection_id": "c1", "job_type": "discover",
    "status": "succeeded", "progress": 100, "message": "Discovered 52 objects",
    "result": {"snapshot_id": "s1", "summary": {"host": 2, "network": 11}},
    "created_at": NOW, "started_at": NOW, "finished_at": NOW,
}

CHANGE = {
    "id": "ch1", "connection_id": "c1", "snapshot_id": "s1", "filename": "changes.xlsx",
    "status": "planned", "error_count": 0, "warning_count": 1, "change_count": 2,
    "validation": {"issues": []},
    "plan": {
        "creates": [{"action": "create", "sheet": "Hosts", "name": "APP01", "payload": {}}],
        "updates": [{"action": "update", "sheet": "Networks", "name": "DMZ", "id": "n1", "payload": {}}],
        "deletes": [],
        "total": 2,
    },
    "deployment": {"ok": True, "applied": 2, "failed": 0, "dry_run": False, "details": []},
    "created_at": NOW,
}

REPORT = {
    "id": "r1", "kind": "validation", "title": "Validation: changes.xlsx",
    "connection_id": "c1", "subject_id": "ch1", "summary": {"errors": 0, "warnings": 1},
    "created_at": NOW,
}

CASES = {
    "login.html": {"error": "Incorrect email or password"},
    "error.html": {"code": 404, "message": "Not found"},
    "change_password.html": {"error": None, "success": "Password updated."},
    "dashboard.html": {
        "connections": [CONNECTION], "jobs": [JOB], "snapshots": [SNAPSHOT],
        "must_change_password": True,
    },
    "connections.html": {
        "connections": [CONNECTION],
        "plugins": [{"key": "secure_firewall", "display_name": "Cisco Secure Firewall (FMC)"}],
    },
    "inventory.html": {
        "snapshot": SNAPSHOT,
        "items": [{"id": "i1", "item_type": "host", "name": "WEB01",
                   "payload": {"value": "10.1.1.1", "description": "web"}}],
        "meta": {"total": 52, "limit": 100, "offset": 0},
        "item_type": "", "search": "", "offset": 0,
    },
    "job.html": {"job": JOB},
    "partials/job_status.html": {"job": JOB},
    "partials/test_result.html": {"result": {"ok": True, "detail": "Connected to FMC 7.4.1"}},
    "changes.html": {
        "changes": [CHANGE], "connections": [CONNECTION],
        "by_connection": {"c1": CONNECTION}, "ready": {"c1"},
    },
    "change_detail.html": {
        "change": CHANGE, "connection": CONNECTION, "reports": [REPORT],
        "issues": [{"severity": "warning", "sheet": "Hosts", "row": 3,
                    "field": "name", "message": "still a member of group WEB-TIER",
                    "remediation": "Remove it from the group in the same upload."}],
    },
    "reports.html": {"reports": [REPORT], "kind": ""},
    "drift.html": {
        "snapshots": [SNAPSHOT, {**SNAPSHOT, "id": "s2"}],
        "connections": [CONNECTION], "reports": [{**REPORT, "kind": "drift"}],
    },
    "audit.html": {
        "events": [{"id": "a1", "actor": USER, "action": "auth.login", "target_type": "user",
                    "target_id": "u1", "outcome": "success", "source_ip": "10.0.0.5",
                    "created_at": NOW}],
        "actor": "", "offset": 0,
    },
}


def test_every_template_has_a_render_case():
    on_disk = {
        str(p.relative_to(TEMPLATE_DIR)).replace("\\", "/")
        for p in TEMPLATE_DIR.rglob("*.html")
        if p.name != "base.html"
    }
    assert on_disk == set(CASES), f"missing render cases for: {sorted(on_disk - set(CASES))}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_template_renders(name: str):
    html = env.get_template(name).render(user=USER, **CASES[name])
    assert html.strip()


def test_pages_render_with_no_data():
    """Empty lists must not blow up the empty-state branches."""
    empty = {
        "dashboard.html": {"connections": [], "jobs": [], "snapshots": [], "must_change_password": False},
        "connections.html": {"connections": [], "plugins": []},
        "changes.html": {"changes": [], "connections": [], "by_connection": {}, "ready": set()},
        "reports.html": {"reports": [], "kind": ""},
        "audit.html": {"events": [], "actor": "", "offset": 0},
        "drift.html": {"snapshots": [], "connections": [], "reports": []},
        "inventory.html": {
            "snapshot": SNAPSHOT, "items": [], "meta": {"total": 0, "limit": 100, "offset": 0},
            "item_type": "", "search": "", "offset": 0,
        },
    }
    for name, ctx in empty.items():
        assert env.get_template(name).render(user=USER, **ctx).strip()


def test_inventory_paging_uses_the_data_not_dict_builtins():
    """Regression: 'page.items' resolved to dict.items and raised TypeError at render."""
    html = env.get_template("inventory.html").render(
        user=USER,
        snapshot=SNAPSHOT,
        items=[{"id": "i1", "item_type": "host", "name": "WEB01", "payload": {"value": "10.1.1.1"}}],
        meta={"total": 250, "limit": 100, "offset": 100},
        item_type="",
        search="",
        offset=100,
    )
    assert "WEB01" in html
    assert "Showing 101-101 of 250" in html
    assert "offset=200" in html  # Next
    assert "offset=0" in html  # Previous

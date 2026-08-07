"""Covers the full validate -> plan -> dry-run path without touching an FMC."""

from app.plugins import registry
from app.plugins.base import DiscoveryResult

PLUGIN = registry.get("secure_firewall")


def _discovery() -> DiscoveryResult:
    return DiscoveryResult(
        product_version="7.4.1",
        items=[
            {"item_type": "host", "external_id": "h1", "name": "WEB01",
             "payload": {"id": "h1", "name": "WEB01", "type": "Host", "value": "10.1.1.1"}},
            {"item_type": "network", "external_id": "n1", "name": "DMZ",
             "payload": {"id": "n1", "name": "DMZ", "type": "Network", "value": "10.2.0.0/24"}},
            {"item_type": "network_group", "external_id": "g1", "name": "WEB-TIER",
             "payload": {"id": "g1", "name": "WEB-TIER", "type": "NetworkGroup",
                         "objects": [{"id": "h1", "name": "WEB01", "type": "Host"}]}},
        ],
        summary={"host": 1, "network": 1, "network_group": 1, "range": 0, "port": 0},
    )


def test_clean_workbook_validates_and_plans():
    rows = {
        "Hosts": [{"action": "create", "name": "APP01", "value": "10.1.1.20", "description": "app"}],
        "Networks": [{"action": "update", "name": "DMZ", "value": "10.2.0.0/23"}],
    }
    result = PLUGIN.validate(rows, _discovery())
    assert result.is_valid, [i.message for i in result.issues]

    plan = PLUGIN.plan(rows, _discovery())
    assert plan.total == 2
    assert plan.creates[0]["payload"]["type"] == "Host"
    assert plan.updates[0]["id"] == "n1"
    assert plan.updates[0]["before"]["value"] == "10.2.0.0/24"


def test_duplicate_names_in_one_sheet_are_errors():
    rows = {
        "Hosts": [
            {"action": "create", "name": "APP01", "value": "10.1.1.20"},
            {"action": "create", "name": "app01", "value": "10.1.1.21"},
        ]
    }
    issues = PLUGIN.validate(rows, _discovery()).issues
    assert any("duplicate" in i.message for i in issues)


def test_network_without_prefix_is_an_error():
    rows = {"Networks": [{"action": "create", "name": "NEW", "value": "10.5.0.0"}]}
    issues = PLUGIN.validate(rows, _discovery()).issues
    assert any("prefix length" in i.message for i in issues)


def test_range_and_port_rules():
    rows = {
        "Ranges": [
            {"action": "create", "name": "POOL-BAD", "value": "10.1.1.50-10.1.1.10"},
            {"action": "create", "name": "POOL-OK", "value": "10.1.1.10-10.1.1.50"},
        ],
        "Ports": [
            {"action": "create", "name": "P-BAD", "protocol": "SCTP", "port": "99999"},
            {"action": "create", "name": "P-OK", "protocol": "tcp", "port": "8080-8090"},
        ],
    }
    issues = PLUGIN.validate(rows, _discovery()).issues
    messages = [i.message for i in issues]
    assert any("end address is before start" in m for m in messages)
    assert any("TCP or UDP" in m for m in messages)
    assert any("not a valid port" in m for m in messages)
    assert not any("P-OK" in m or "POOL-OK" in m for m in messages)


def test_group_members_must_exist_or_be_created_in_the_same_workbook():
    rows = {
        "Hosts": [{"action": "create", "name": "APP01", "value": "10.1.1.20"}],
        "NetworkGroups": [
            {"action": "create", "name": "APP-TIER", "members": "APP01, WEB01"},
            {"action": "create", "name": "BROKEN", "members": "DOES-NOT-EXIST"},
        ],
    }
    issues = PLUGIN.validate(rows, _discovery()).issues
    messages = [i.message for i in issues]
    assert any("DOES-NOT-EXIST" in m for m in messages)
    assert not any("APP01' does not exist" in m for m in messages)


def test_deleting_a_group_member_raises_a_warning_not_an_error():
    rows = {"Hosts": [{"action": "delete", "name": "WEB01"}]}
    result = PLUGIN.validate(rows, _discovery())
    assert result.is_valid
    assert any(i.severity == "warning" and "WEB-TIER" in i.message for i in result.issues)


def test_plan_orders_groups_after_their_members_and_reverses_deletes():
    rows = {
        "Hosts": [{"action": "create", "name": "APP01", "value": "10.1.1.20"}],
        "NetworkGroups": [{"action": "create", "name": "APP-TIER", "members": "APP01"}],
    }
    plan = PLUGIN.plan(rows, _discovery())
    assert [e["sheet"] for e in plan.creates] == ["Hosts", "NetworkGroups"]

    delete_rows = {
        "Hosts": [{"action": "delete", "name": "WEB01"}],
        "NetworkGroups": [{"action": "delete", "name": "WEB-TIER"}],
    }
    delete_plan = PLUGIN.plan(delete_rows, _discovery())
    assert [e["sheet"] for e in delete_plan.deletes] == ["NetworkGroups", "Hosts"]


def test_group_payload_resolves_members_to_ids():
    rows = {"NetworkGroups": [{"action": "create", "name": "APP-TIER", "members": "WEB01,DMZ"}]}
    plan = PLUGIN.plan(rows, _discovery())
    objects = plan.creates[0]["payload"]["objects"]
    assert {o["id"] for o in objects} == {"h1", "n1"}


def test_dry_run_reports_every_operation_and_applies_nothing():
    rows = {
        "Hosts": [{"action": "create", "name": "APP01", "value": "10.1.1.20"}],
        "Networks": [{"action": "update", "name": "DMZ", "value": "10.2.0.0/23"}],
    }
    plan = PLUGIN.plan(rows, _discovery())
    result = PLUGIN.deploy(ctx=None, plan=plan, engine="rest", dry_run=True)  # type: ignore[arg-type]

    assert result.ok
    assert result.applied == 0
    assert len(result.details) == 2
    assert {d["status"] for d in result.details} == {"planned"}


def test_unimplemented_engines_fail_loudly():
    import pytest

    plan = PLUGIN.plan({}, _discovery())
    with pytest.raises(NotImplementedError):
        PLUGIN.deploy(ctx=None, plan=plan, engine="ansible", dry_run=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PLUGIN.deploy(ctx=None, plan=plan, engine="carrier-pigeon", dry_run=True)  # type: ignore[arg-type]


def test_populated_but_undeployable_sheet_warns_instead_of_silently_ignoring():
    rows = {
        "AccessRules": [
            {"action": "create", "policy": "ACP1", "rule_name": "allow-web"},
            {"action": "create", "policy": "ACP1", "rule_name": "allow-dns"},
            {"action": "", "policy": "", "rule_name": ""},
        ]
    }
    result = PLUGIN.validate(rows, _discovery())

    assert result.is_valid  # a warning must not block the rest of the workbook
    warnings = [i for i in result.issues if i.severity == "warning"]
    assert len(warnings) == 1
    assert "2 row(s)" in warnings[0].message
    assert warnings[0].sheet == "AccessRules"


def test_empty_unsupported_sheet_is_silent():
    rows = {"AccessRules": [{"action": "", "rule_name": ""}]}
    assert PLUGIN.validate(rows, _discovery()).issues == []

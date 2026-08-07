"""Access control rules must validate, plan, deploy and roll back like any other object."""

import pytest

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
            {"item_type": "port", "external_id": "p1", "name": "HTTPS",
             "payload": {"id": "p1", "name": "HTTPS", "type": "ProtocolPortObject",
                         "protocol": "TCP", "port": "443"}},
            {"item_type": "access_policy", "external_id": "acp1", "name": "Corp-ACP",
             "payload": {"id": "acp1", "name": "Corp-ACP"}},
            {"item_type": "access_rule", "external_id": "r1", "name": "allow-web",
             "payload": {"id": "r1", "name": "allow-web", "action": "ALLOW",
                         "_policyName": "Corp-ACP", "_policyId": "acp1"}},
        ],
        summary={"host": 1, "network": 1, "port": 1, "access_policy": 1, "access_rule": 1},
    )


def _issues(rows, severity=None):
    return [
        i for i in PLUGIN.validate(rows, _discovery()).issues
        if severity is None or i.severity == severity
    ]


def test_access_rules_are_no_longer_reference_only():
    assert "AccessRules" not in PLUGIN.reference_sheets


def test_a_valid_new_rule_passes_and_plans():
    rows = {
        "AccessRules": [{
            "action": "create", "policy": "Corp-ACP", "rule_name": "allow-dns",
            "rule_action": "ALLOW", "enabled": "true",
            "source_networks": "DMZ", "destination_networks": "10.8.8.8",
            "destination_ports": "HTTPS", "log_begin": "true",
        }]
    }
    assert PLUGIN.validate(rows, _discovery()).is_valid, [i.message for i in _issues(rows)]

    plan = PLUGIN.plan(rows, _discovery())
    assert plan.total == 1
    entry = plan.creates[0]
    assert entry["target"] == "access_rule"
    assert entry["policy_id"] == "acp1"
    assert entry["payload"]["action"] == "ALLOW"
    assert entry["payload"]["sourceNetworks"]["objects"][0]["id"] == "n1"
    assert entry["payload"]["destinationNetworks"]["literals"][0]["value"] == "10.8.8.8"
    assert entry["payload"]["destinationPorts"]["objects"][0]["id"] == "p1"
    assert entry["payload"]["logBegin"] is True


def test_unknown_policy_is_rejected():
    rows = {"AccessRules": [{"action": "create", "policy": "Nope", "rule_name": "r",
                             "rule_action": "ALLOW"}]}
    assert any("does not exist on the FMC" in i.message for i in _issues(rows, "error"))


def test_duplicate_rule_in_same_policy_is_rejected():
    rows = {"AccessRules": [
        {"action": "create", "policy": "Corp-ACP", "rule_name": "new", "rule_action": "ALLOW"},
        {"action": "create", "policy": "Corp-ACP", "rule_name": "NEW", "rule_action": "ALLOW"},
    ]}
    assert any("duplicate of row 2" in i.message for i in _issues(rows, "error"))


def test_creating_an_existing_rule_is_rejected():
    rows = {"AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "allow-web",
                             "rule_action": "ALLOW"}]}
    assert any("already exists in policy" in i.message for i in _issues(rows, "error"))


def test_updating_a_missing_rule_is_rejected():
    rows = {"AccessRules": [{"action": "update", "policy": "Corp-ACP", "rule_name": "ghost",
                             "rule_action": "ALLOW"}]}
    assert any("does not exist in policy" in i.message for i in _issues(rows, "error"))


def test_invalid_rule_action_lists_the_allowed_values():
    rows = {"AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "r",
                             "rule_action": "PERMIT"}]}
    issue = next(i for i in _issues(rows, "error") if i.field == "rule_action")
    assert "ALLOW" in issue.remediation and "BLOCK" in issue.remediation


def test_unknown_network_reference_is_rejected_but_literals_are_allowed():
    rows = {"AccessRules": [{
        "action": "create", "policy": "Corp-ACP", "rule_name": "r", "rule_action": "ALLOW",
        "source_networks": "TYPO-OBJ", "destination_networks": "10.9.0.0/24",
    }]}
    messages = [i.message for i in _issues(rows, "error")]
    assert any("TYPO-OBJ" in m for m in messages)
    assert not any("10.9.0.0/24" in m for m in messages)


def test_a_rule_may_reference_an_object_created_in_the_same_workbook():
    rows = {
        "Hosts": [{"action": "create", "name": "APP01", "value": "10.1.1.30"}],
        "AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "r",
                         "rule_action": "ALLOW", "source_networks": "APP01"}],
    }
    assert PLUGIN.validate(rows, _discovery()).is_valid


def test_objects_are_created_before_the_rules_that_use_them():
    rows = {
        "Hosts": [{"action": "create", "name": "APP01", "value": "10.1.1.30"}],
        "AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "r",
                         "rule_action": "ALLOW", "source_networks": "APP01"}],
    }
    plan = PLUGIN.plan(rows, _discovery())
    assert [e["sheet"] for e in plan.creates] == ["Hosts", "AccessRules"]


def test_rules_are_deleted_before_the_objects_they_reference():
    rows = {
        "Hosts": [{"action": "delete", "name": "WEB01"}],
        "AccessRules": [{"action": "delete", "policy": "Corp-ACP", "rule_name": "allow-web"}],
    }
    plan = PLUGIN.plan(rows, _discovery())
    assert [e["sheet"] for e in plan.deletes] == ["AccessRules", "Hosts"]


def test_dry_run_covers_rules_without_contacting_anything():
    rows = {"AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "r",
                             "rule_action": "BLOCK"}]}
    result = PLUGIN.deploy(ctx=None, plan=PLUGIN.plan(rows, _discovery()), dry_run=True)  # type: ignore[arg-type]
    assert result.ok and result.applied == 0
    assert result.details[0]["status"] == "planned"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("yes", True), ("false", False), ("no", False), ("", True)],
)
def test_enabled_accepts_the_spellings_people_actually_type(value, expected):
    rows = {"AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "r",
                             "rule_action": "ALLOW", "enabled": value}]}
    assert PLUGIN.plan(rows, _discovery()).creates[0]["payload"]["enabled"] is expected


def test_preview_emits_runnable_curl_for_a_rule():
    rows = {"AccessRules": [{"action": "create", "policy": "Corp-ACP", "rule_name": "allow-dns",
                             "rule_action": "ALLOW"}]}
    call = PLUGIN.preview(PLUGIN.plan(rows, _discovery()), host="198.18.1.10")[0]

    assert call["method"] == "POST"
    assert "198.18.1.10" in call["path"]
    assert "/policy/accesspolicies/acp1/accessrules" in call["path"]
    assert call["cli"].startswith("curl -k -X POST")
    assert "X-auth-access-token: $TOKEN" in call["cli"]
    assert '"name": "allow-dns"' in call["cli"]


def test_preview_of_an_object_delete_has_no_body():
    call = PLUGIN.preview(
        PLUGIN.plan({"Hosts": [{"action": "delete", "name": "WEB01"}]}, _discovery()),
        host="198.18.1.10",
    )[0]
    assert call["method"] == "DELETE"
    assert call["body"] is None
    assert "-d " not in call["cli"]

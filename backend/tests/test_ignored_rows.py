"""A workbook full of edits with no action set must not look like success."""

from app.plugins import registry
from app.plugins.base import DiscoveryResult

PLUGIN = registry.get("secure_firewall")


def _discovery() -> DiscoveryResult:
    return DiscoveryResult(
        product_version="7.4.1",
        items=[
            {"item_type": "host", "external_id": "h1", "name": "WEB01",
             "payload": {"id": "h1", "name": "WEB01", "type": "Host",
                         "value": "10.1.1.1", "description": "web"}},
            {"item_type": "network", "external_id": "n1", "name": "DMZ",
             "payload": {"id": "n1", "name": "DMZ", "type": "Network", "value": "10.2.0.0/24"}},
            {"item_type": "network_group", "external_id": "g1", "name": "WEB-TIER",
             "payload": {"id": "g1", "name": "WEB-TIER", "type": "NetworkGroup",
                         "objects": [{"id": "h1", "name": "WEB01", "type": "Host"}]}},
        ],
        summary={"host": 1, "network": 1, "network_group": 1},
    )


def _messages(rows, severity=None):
    issues = PLUGIN.validate(rows, _discovery()).issues
    return [i.message for i in issues if severity is None or i.severity == severity]


def test_unchanged_export_produces_no_noise():
    rows = {
        "Hosts": [{"action": "", "name": "WEB01", "value": "10.1.1.1", "description": "web"}],
        "Networks": [{"action": "", "name": "DMZ", "value": "10.2.0.0/24", "description": ""}],
    }
    assert PLUGIN.validate(rows, _discovery()).issues == []


def test_edited_row_without_an_action_is_flagged():
    rows = {"Hosts": [{"action": "", "name": "WEB01", "value": "10.9.9.9", "description": "web"}]}
    warnings = _messages(rows, "warning")
    assert any("differs from the FMC" in m and "value" in m for m in warnings)
    assert any("action=update" in m for m in warnings)


def test_new_row_without_an_action_is_flagged():
    rows = {"Hosts": [{"action": "", "name": "APP99", "value": "10.4.4.4", "description": ""}]}
    warnings = _messages(rows, "warning")
    assert any("not on the FMC" in m and "action=create" in m for m in warnings)


def test_duplicate_rows_are_errors_even_with_no_action():
    rows = {
        "Hosts": [
            {"action": "", "name": "WEB01", "value": "10.1.1.1", "description": "web"},
            {"action": "", "name": "web01", "value": "10.1.1.1", "description": "web"},
        ]
    }
    errors = _messages(rows, "error")
    assert any("duplicate of row 2" in m for m in errors)


def test_duplicate_created_object_is_still_an_error():
    rows = {
        "Hosts": [
            {"action": "create", "name": "APP01", "value": "10.5.5.1"},
            {"action": "create", "name": "APP01", "value": "10.5.5.2"},
        ]
    }
    errors = _messages(rows, "error")
    assert any("duplicate of row 2" in m for m in errors)


def test_creating_something_that_already_exists_is_an_error():
    rows = {"Hosts": [{"action": "create", "name": "WEB01", "value": "10.1.1.1"}]}
    assert any("already exists on the FMC" in m for m in _messages(rows, "error"))


def test_group_membership_change_without_an_action_is_flagged():
    rows = {"NetworkGroups": [{"action": "", "name": "WEB-TIER", "members": "WEB01, DMZ"}]}
    assert any("members" in m for m in _messages(rows, "warning"))


def test_group_member_order_alone_is_not_a_change():
    rows = {"NetworkGroups": [{"action": "", "name": "WEB-TIER", "members": " web01 "}]}
    assert PLUGIN.validate(rows, _discovery()).issues == []


def test_warnings_do_not_block_a_valid_change():
    rows = {
        "Hosts": [
            {"action": "", "name": "WEB01", "value": "10.9.9.9"},          # edited, no action
            {"action": "create", "name": "APP01", "value": "10.5.5.1"},    # real change
        ]
    }
    result = PLUGIN.validate(rows, _discovery())
    assert result.is_valid
    assert PLUGIN.plan(rows, _discovery()).total == 1

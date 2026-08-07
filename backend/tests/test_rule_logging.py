"""The FMC rejects a rule that logs with no destination. Catch it before deploying."""

from app.plugins import registry
from app.plugins.base import DiscoveryResult

PLUGIN = registry.get("secure_firewall")


def _discovery() -> DiscoveryResult:
    return DiscoveryResult(
        product_version="7.4.1",
        items=[
            {"item_type": "access_policy", "external_id": "acp1", "name": "Corp-ACP",
             "payload": {"id": "acp1", "name": "Corp-ACP"}},
        ],
        summary={"access_policy": 1},
    )


def _rule(**overrides):
    row = {
        "action": "create", "policy": "Corp-ACP",
        "rule_name": "New-Rule-#1-ALLOW-6", "rule_action": "ALLOW",
    }
    row.update(overrides)
    return {"AccessRules": [row]}


def _payload(rows):
    return PLUGIN.plan(rows, _discovery()).creates[0]["payload"]


def test_logging_adds_a_destination_so_the_fmc_accepts_the_rule():
    """Regression: HTTP 400 'Provide at least one destination for Connection Events'."""
    assert _payload(_rule(log_end="true"))["sendEventsToFMC"] is True
    assert _payload(_rule(log_begin="true"))["sendEventsToFMC"] is True


def test_no_logging_means_no_destination_field():
    payload = _payload(_rule(log_begin="false", log_end="false"))
    assert payload["logBegin"] is False
    assert payload["logEnd"] is False
    assert "sendEventsToFMC" not in payload


def test_logging_with_the_destination_switched_off_is_rejected_before_deploying():
    issues = PLUGIN.validate(_rule(log_end="true", send_events_to_fmc="false"), _discovery()).issues
    error = next(i for i in issues if i.severity == "error")
    assert "no destination" in error.message
    assert "send_events_to_fmc" in error.remediation


def test_explicit_destination_is_honoured():
    assert _payload(_rule(log_end="true", send_events_to_fmc="true"))["sendEventsToFMC"] is True


def test_applications_column_warns_rather_than_silently_dropping():
    issues = PLUGIN.validate(_rule(applications="HTTP, DNS"), _discovery()).issues
    warning = next(i for i in issues if i.field == "applications")
    assert warning.severity == "warning"
    assert "ignored" in warning.message


def test_urls_are_sent_as_literals_when_not_an_object():
    payload = _payload(_rule(urls="http://example.com/bad"))
    assert payload["urls"]["literals"][0]["url"] == "http://example.com/bad"

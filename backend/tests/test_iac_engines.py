"""The generated Ansible and Terraform must be runnable, not decorative."""

import json
import re

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
            {"item_type": "access_policy", "external_id": "acp1", "name": "Corp-ACP",
             "payload": {"id": "acp1", "name": "Corp-ACP"}},
        ],
        summary={"host": 1, "network": 1, "access_policy": 1},
    )


def _plan(rows):
    return PLUGIN.plan(rows, _discovery())


ROWS = {
    "Hosts": [
        {"action": "create", "name": "APP01", "value": "10.1.1.30", "description": "app tier"},
        {"action": "delete", "name": "WEB01"},
    ],
    "Networks": [{"action": "update", "name": "DMZ", "value": "10.2.0.0/23"}],
    "AccessRules": [{
        "action": "create", "policy": "Corp-ACP", "rule_name": "allow-app",
        "rule_action": "ALLOW", "source_networks": "DMZ", "log_end": "true",
    }],
}


# -- Ansible ---------------------------------------------------------------
def _playbook() -> str:
    return PLUGIN.render_artifacts(_plan(ROWS), "ansible", "changes.xlsx", "198.18.1.10")["fmc_change.yml"]


def test_playbook_authenticates_before_making_changes():
    text = _playbook()
    assert text.index("auth/generatetoken") < text.index("object/hosts")
    assert "x_auth_access_token" in text
    assert "domain_uuid" in text


def test_playbook_uses_only_builtin_modules():
    """No external collection to install, so it runs anywhere Ansible does."""
    modules = set(re.findall(r"^\s+(\S+\.\S+\.\S+):", _playbook(), re.M))
    assert modules <= {"ansible.builtin.uri", "ansible.builtin.set_fact"}


def test_playbook_never_logs_the_credentials():
    text = _playbook()
    assert text.count("no_log: true") >= 2
    assert "FMC_PASSWORD" in text  # taken from the environment, not embedded


def test_playbook_has_a_task_per_operation_with_the_right_verb():
    text = _playbook()
    assert "method: POST" in text
    assert "method: PUT" in text
    assert "method: DELETE" in text
    assert "1. create host APP01" in text


def test_playbook_bodies_are_valid_json():
    for body in re.findall(r"^\s+body: (\{.*\})$", _playbook(), re.M):
        json.loads(body)


def test_delete_task_sends_no_body():
    tasks = _playbook().split("    - name: ")
    delete_task = next(t for t in tasks if "delete host WEB01" in t)
    assert "method: DELETE" in delete_task
    assert "body:" not in delete_task


def test_empty_plan_still_produces_a_valid_playbook():
    text = PLUGIN.render_artifacts(_plan({}), "ansible", "c.xlsx", "10.0.0.1")["fmc_change.yml"]
    assert text.startswith("---")
    assert "no operations" in text


# -- Terraform -------------------------------------------------------------
def _terraform() -> dict[str, str]:
    return PLUGIN.render_artifacts(_plan(ROWS), "terraform", "changes.xlsx", "198.18.1.10")


def test_terraform_ships_provider_variables_and_resources():
    files = _terraform()
    assert set(files) == {"providers.tf", "variables.tf", "main.tf", "README.md"}
    assert "CiscoDevNet/fmc" in files["providers.tf"]


def test_credentials_are_variables_and_marked_sensitive():
    variables = _terraform()["variables.tf"]
    assert variables.count("sensitive   = true") == 2
    assert "TF_VAR_fmc_username" in variables


def test_resources_use_the_correct_types():
    main = _terraform()["main.tf"]
    assert 'resource "fmc_host_objects" "app01"' in main
    assert 'resource "fmc_network_objects" "dmz"' in main
    assert 'resource "fmc_access_rules" "allow_app"' in main
    assert 'value = "10.1.1.30"' in main


def test_deletes_are_explained_rather_than_silently_dropped():
    """Terraform removes objects by deleting the block, which a generator cannot express."""
    main = _terraform()["main.tf"]
    assert "cannot be expressed here" in main
    assert "delete host WEB01" in main


def test_readme_warns_that_state_import_is_required():
    readme = _terraform()["README.md"]
    assert "terraform import" in readme
    assert "duplicates" in readme


def test_identifiers_are_valid_hcl():
    plan = _plan({"Hosts": [{"action": "create", "name": "9-web server(!)", "value": "10.1.1.5"}]})
    main = PLUGIN.render_artifacts(plan, "terraform", "c.xlsx", "h")["main.tf"]
    identifier = re.search(r'resource "fmc_host_objects" "([^"]+)"', main).group(1)
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier)


def test_quotes_in_a_name_cannot_break_out_of_the_string():
    plan = _plan({"Hosts": [{"action": "create", "name": 'we"b', "value": "10.1.1.5"}]})
    main = PLUGIN.render_artifacts(plan, "terraform", "c.xlsx", "h")["main.tf"]
    assert r'name = "we\"b"' in main


def test_an_unknown_engine_is_rejected():
    with pytest.raises(ValueError):
        PLUGIN.render_artifacts(_plan(ROWS), "puppet", "c.xlsx", "h")


def test_deploying_with_a_generation_engine_explains_the_alternative():
    with pytest.raises(NotImplementedError, match="download it"):
        PLUGIN.deploy(ctx=None, plan=_plan(ROWS), engine="terraform", dry_run=False)  # type: ignore[arg-type]

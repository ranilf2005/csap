from app.plugins import registry
from app.plugins.base import DiscoveryResult
from app.services.templates import build_workbook


def _discovery() -> DiscoveryResult:
    return DiscoveryResult(
        product_version="7.4.1",
        items=[
            {"item_type": "host", "external_id": "1", "name": "WEB01", "payload": {}},
            {"item_type": "network", "external_id": "2", "name": "DMZ", "payload": {}},
        ],
        summary={"host": 1, "network": 1},
    )


def test_secure_firewall_plugin_is_registered():
    keys = [p.manifest.key for p in registry.available()]
    assert "secure_firewall" in keys


def test_template_spec_drops_absent_entity_sheets():
    plugin = registry.get("secure_firewall")
    spec = plugin.template_spec(_discovery())
    assert "Hosts" in spec
    assert "Ranges" not in spec  # no ranges discovered


def test_workbook_is_generated_for_every_sheet():
    plugin = registry.get("secure_firewall")
    spec = plugin.template_spec(_discovery())
    content = build_workbook(spec, "secure_firewall", "7.4.1")
    assert content[:2] == b"PK"  # xlsx is a zip archive

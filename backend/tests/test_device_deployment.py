"""Pushing to the FMC and deploying to the FTDs are separate, explicit steps."""

from typing import Any

from app.plugins import registry

PLUGIN = registry.get("secure_firewall")


class FakeFmc:
    """Stands in for the FMC so the deployment handshake can be tested offline."""

    def __init__(self, deployable: list[dict[str, Any]], statuses: list[str]):
        self.deployable = deployable
        self.statuses = statuses
        self.requested: dict[str, Any] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def list_deployable_devices(self):
        return self.deployable

    def request_deployment(self, device_ids, version, force=False, ignore_warning=True):
        self.requested = {"deviceList": device_ids, "version": version, "forceDeploy": force}
        return {"metadata": {"task": {"id": "task-1"}}}

    def task_status(self, task_id):
        return {"status": self.statuses.pop(0) if self.statuses else "Deployed", "message": "ok"}


def _patch(monkeypatch, fake, no_sleep=True):
    monkeypatch.setattr(PLUGIN, "_client", lambda ctx: fake)
    if no_sleep:
        monkeypatch.setattr("app.plugins.secure_firewall.plugin.time.sleep", lambda _s: None)


def test_only_selected_devices_are_deployed_to(monkeypatch):
    fake = FakeFmc(
        [
            {"deviceId": "d1", "name": "FTD-1", "version": "100", "canBeDeployed": True},
            {"deviceId": "d2", "name": "FTD-2", "version": "200", "canBeDeployed": True},
        ],
        ["Deployed"],
    )
    _patch(monkeypatch, fake)

    result = PLUGIN.push_to_devices(ctx=None, device_ids=["d1"])  # type: ignore[arg-type]

    assert result["ok"] is True
    assert fake.requested["deviceList"] == ["d1"]
    assert [d["name"] for d in result["devices"]] == ["FTD-1"]


def test_the_newest_pending_version_is_sent(monkeypatch):
    """An older version makes the FMC reject the request."""
    fake = FakeFmc(
        [
            {"deviceId": "d1", "name": "FTD-1", "version": "100", "canBeDeployed": True},
            {"deviceId": "d2", "name": "FTD-2", "version": "300", "canBeDeployed": True},
        ],
        ["Deployed"],
    )
    _patch(monkeypatch, fake)

    PLUGIN.push_to_devices(ctx=None, device_ids=["d1", "d2"])  # type: ignore[arg-type]
    assert fake.requested["version"] == "300"


def test_devices_the_fmc_cannot_deploy_are_skipped(monkeypatch):
    fake = FakeFmc(
        [{"deviceId": "d1", "name": "FTD-1", "version": "100", "canBeDeployed": False}], ["Deployed"]
    )
    _patch(monkeypatch, fake)

    result = PLUGIN.push_to_devices(ctx=None, device_ids=["d1"])  # type: ignore[arg-type]
    assert result["skipped"] is True
    assert result["ok"] is True
    assert fake.requested is None


def test_nothing_pending_is_reported_not_treated_as_failure(monkeypatch):
    _patch(monkeypatch, FakeFmc([], []))
    result = PLUGIN.push_to_devices(ctx=None, device_ids=["d1"])  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["skipped"] is True


def test_a_failed_deployment_is_reported(monkeypatch):
    _patch(monkeypatch, FakeFmc(
        [{"deviceId": "d1", "name": "FTD-1", "version": "100", "canBeDeployed": True}],
        ["Deploying", "Failed"],
    ))
    result = PLUGIN.push_to_devices(ctx=None, device_ids=["d1"])  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["state"] == "Failed"


def test_polling_gives_up_rather_than_hanging(monkeypatch):
    _patch(monkeypatch, FakeFmc(
        [{"deviceId": "d1", "name": "FTD-1", "version": "100", "canBeDeployed": True}],
        ["Deploying"] * 50,
    ))
    result = PLUGIN.push_to_devices(ctx=None, device_ids=["d1"], poll_seconds=30)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["timed_out"] is True


def test_the_alternate_device_shape_is_understood(monkeypatch):
    """Some FMC versions nest the device instead of returning deviceId."""
    fake = FakeFmc(
        [{"device": {"id": "d9", "name": "FTD-9"}, "version": "400", "canBeDeployed": True}],
        ["Deployed"],
    )
    _patch(monkeypatch, fake)

    result = PLUGIN.push_to_devices(ctx=None, device_ids=["d9"])  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["devices"][0]["name"] == "FTD-9"

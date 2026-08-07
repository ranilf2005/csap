"""Minimal, dependency-light Cisco Secure Firewall Management Center REST client.

Handles token generation/refresh, domain selection, pagination and FMC's
120-requests-per-minute throttle.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

PLATFORM = "/api/fmc_platform/v1"
CONFIG = "/api/fmc_config/v1"
PAGE_SIZE = 1000


class FmcError(RuntimeError):
    pass


class FmcAuthError(FmcError):
    pass


class FmcRateLimited(FmcError):
    pass


class FmcClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_tls: bool = True,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = f"https://{host}:{port}"
        self._username = username
        self._password = password
        self._client = httpx.Client(
            base_url=self._base_url,
            verify=verify_tls,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._domain_uuid: str | None = None
        self._domains: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._last_call = 0.0

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> FmcClient:
        self.login()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- auth --------------------------------------------------------------
    def login(self) -> None:
        resp = self._client.post(
            f"{PLATFORM}/auth/generatetoken",
            auth=(self._username, self._password),
            content=b"",
        )
        if resp.status_code == 401:
            raise FmcAuthError("FMC rejected the credentials (401)")
        if resp.status_code != 204 and resp.status_code >= 400:
            raise FmcAuthError(f"FMC token request failed: HTTP {resp.status_code}")

        self._token = resp.headers.get("X-auth-access-token")
        self._refresh_token = resp.headers.get("X-auth-refresh-token")
        if not self._token:
            raise FmcAuthError("FMC did not return an access token")

        self._domain_uuid = resp.headers.get("DOMAIN_UUID")
        raw_domains = resp.headers.get("DOMAINS")
        if raw_domains:
            self._domains = json.loads(raw_domains)
            if not self._domain_uuid and self._domains:
                self._domain_uuid = self._domains[0]["uuid"]
        self._client.headers["X-auth-access-token"] = self._token
        logger.info("authenticated to FMC %s (domain %s)", self._base_url, self._domain_uuid)

    @property
    def domain_uuid(self) -> str:
        if not self._domain_uuid:
            raise FmcError("no FMC domain selected; call login() first")
        return self._domain_uuid

    @property
    def domains(self) -> list[dict[str, str]]:
        return self._domains

    def use_domain(self, name_or_uuid: str) -> None:
        for domain in self._domains:
            if name_or_uuid in (domain.get("uuid"), domain.get("name")):
                self._domain_uuid = domain["uuid"]
                return
        raise FmcError(f"domain '{name_or_uuid}' not found on this FMC")

    # -- request plumbing --------------------------------------------------
    def _throttle(self) -> None:
        # FMC permits ~120 requests/minute; keep a 0.5s floor between calls.
        with self._lock:
            delta = time.monotonic() - self._last_call
            if delta < 0.5:
                time.sleep(0.5 - delta)
            self._last_call = time.monotonic()

    @retry(
        retry=retry_if_exception_type((FmcRateLimited, httpx.TransportError)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self._token:
            self.login()
        self._throttle()
        resp = self._client.request(method, path, **kwargs)

        if resp.status_code == 401:
            logger.info("FMC token expired; re-authenticating")
            self.login()
            self._throttle()
            resp = self._client.request(method, path, **kwargs)
        if resp.status_code == 429:
            raise FmcRateLimited("FMC rate limit hit (429)")
        if resp.status_code >= 400:
            raise FmcError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
        if not resp.content:
            return {}
        return resp.json()

    def get_paginated(self, path: str, expanded: bool = True) -> list[dict[str, Any]]:
        """Follow FMC's offset/limit paging and return every item."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            params = {"offset": offset, "limit": PAGE_SIZE}
            if expanded:
                params["expanded"] = "true"
            data = self.request("GET", path, params=params)
            page = data.get("items", [])
            items.extend(page)
            paging = data.get("paging", {})
            if len(page) < PAGE_SIZE or not paging.get("next"):
                break
            offset += PAGE_SIZE
        return items

    # -- typed helpers -----------------------------------------------------
    def server_version(self) -> str | None:
        data = self.request("GET", f"{PLATFORM}/info/serverversion", params={"expanded": "true"})
        items = data.get("items") or []
        return items[0].get("serverVersion") if items else None

    def cfg(self, suffix: str) -> str:
        return f"{CONFIG}/domain/{self.domain_uuid}/{suffix.lstrip('/')}"

    def list_objects(self, kind: str) -> list[dict[str, Any]]:
        return self.get_paginated(self.cfg(f"object/{kind}"))

    def list_devices(self) -> list[dict[str, Any]]:
        return self.get_paginated(self.cfg("devices/devicerecords"))

    def list_access_policies(self) -> list[dict[str, Any]]:
        return self.get_paginated(self.cfg("policy/accesspolicies"))

    def list_access_rules(self, policy_id: str) -> list[dict[str, Any]]:
        return self.get_paginated(self.cfg(f"policy/accesspolicies/{policy_id}/accessrules"))

    def list_nat_policies(self) -> list[dict[str, Any]]:
        return self.get_paginated(self.cfg("policy/ftdnatpolicies"))

    def list_nat_rules(self, policy_id: str) -> list[dict[str, Any]]:
        return self.get_paginated(self.cfg(f"policy/ftdnatpolicies/{policy_id}/natrules"))

    def create_object(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", self.cfg(f"object/{kind}"), json=payload)

    def update_object(self, kind: str, object_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        # FMC requires the id inside the body as well as in the path.
        body = {**payload, "id": object_id}
        return self.request("PUT", self.cfg(f"object/{kind}/{object_id}"), json=body)

    def delete_object(self, kind: str, object_id: str) -> dict[str, Any]:
        return self.request("DELETE", self.cfg(f"object/{kind}/{object_id}"))

    def get_object(self, kind: str, object_id: str) -> dict[str, Any]:
        return self.request("GET", self.cfg(f"object/{kind}/{object_id}"))

    # -- access rules ------------------------------------------------------
    def create_access_rule(self, policy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", self.cfg(f"policy/accesspolicies/{policy_id}/accessrules"), json=payload)

    def update_access_rule(self, policy_id: str, rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {**payload, "id": rule_id}
        return self.request(
            "PUT", self.cfg(f"policy/accesspolicies/{policy_id}/accessrules/{rule_id}"), json=body
        )

    def delete_access_rule(self, policy_id: str, rule_id: str) -> dict[str, Any]:
        return self.request("DELETE", self.cfg(f"policy/accesspolicies/{policy_id}/accessrules/{rule_id}"))

    # -- deployment to managed devices -------------------------------------
    def list_deployable_devices(self) -> list[dict[str, Any]]:
        """Devices with configuration staged on the FMC but not yet pushed to them."""
        return self.get_paginated(self.cfg("deployment/deployabledevices"))

    def request_deployment(
        self,
        device_ids: list[str],
        version: str,
        force: bool = False,
        ignore_warning: bool = True,
    ) -> dict[str, Any]:
        body = {
            "type": "DeploymentRequest",
            "version": str(version),
            "forceDeploy": force,
            "ignoreWarning": ignore_warning,
            "deviceList": device_ids,
        }
        return self.request("POST", self.cfg("deployment/deploymentrequests"), json=body)

    def task_status(self, task_id: str) -> dict[str, Any]:
        return self.request("GET", self.cfg(f"job/taskstatuses/{task_id}"))

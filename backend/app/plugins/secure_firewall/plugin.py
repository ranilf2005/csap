"""Cisco Secure Firewall (FMC) plugin - the reference implementation of SecurityPlugin."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from app.plugins.base import (
    ChangePlan,
    ConnectionContext,
    ConnectionResult,
    DeploymentResult,
    DiscoveryResult,
    PluginManifest,
    ProgressCallback,
    SecurityPlugin,
    ValidationIssue,
    ValidationResult,
)
from app.plugins.secure_firewall.fmc_client import FmcAuthError, FmcClient, FmcError

logger = logging.getLogger(__name__)

# FMC object endpoint -> CSAP entity type
OBJECT_KINDS: dict[str, str] = {
    "hosts": "host",
    "networks": "network",
    "ranges": "range",
    "networkgroups": "network_group",
    "protocolportobjects": "port",
    "portobjectgroups": "port_group",
    "urls": "url",
    "urlgroups": "url_group",
}

# Workbook sheet -> (CSAP entity type, FMC endpoint, FMC object type)
SHEET_MAP: dict[str, tuple[str, str, str]] = {
    "Hosts": ("host", "hosts", "Host"),
    "Networks": ("network", "networks", "Network"),
    "Ranges": ("range", "ranges", "Range"),
    "Ports": ("port", "protocolportobjects", "ProtocolPortObject"),
    "NetworkGroups": ("network_group", "networkgroups", "NetworkGroup"),
}

# Plain objects must exist before groups can reference them.
APPLY_ORDER = ["Hosts", "Networks", "Ranges", "Ports", "NetworkGroups"]

VALID_ACTIONS = {"create", "update", "delete"}
GROUP_MEMBER_ENTITIES = ("host", "network", "range", "network_group")

# Sheets the template offers for planning but that cannot be deployed yet.
UNSUPPORTED_SHEETS = {"AccessRules": "0.4 (access rule support)"}


class SecureFirewallPlugin(SecurityPlugin):
    manifest = PluginManifest(
        key="secure_firewall",
        display_name="Cisco Secure Firewall (FMC)",
        description="Discovery, validation and deployment against Firewall Management Center.",
        engines=("rest", "ansible", "terraform"),
        entity_types=(*OBJECT_KINDS.values(), "device", "access_policy", "access_rule", "nat_policy"),
        min_product_version="6.7",
    )

    # -- connect -----------------------------------------------------------
    def _client(self, ctx: ConnectionContext) -> FmcClient:
        return FmcClient(
            host=ctx.host,
            username=ctx.username,
            password=ctx.password,
            port=ctx.port,
            verify_tls=ctx.verify_tls,
        )

    def test_connection(self, ctx: ConnectionContext) -> ConnectionResult:
        try:
            with self._client(ctx) as fmc:
                version = fmc.server_version()
                return ConnectionResult(
                    ok=True,
                    product_version=version,
                    detail=f"Connected to FMC {version or 'unknown version'}",
                )
        except FmcAuthError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        except FmcError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        except Exception as exc:  # network/TLS failures surface here
            return ConnectionResult(ok=False, detail=f"{type(exc).__name__}: {exc}")

    # -- discover ----------------------------------------------------------
    def discover(self, ctx: ConnectionContext, progress: ProgressCallback | None = None) -> DiscoveryResult:
        def report(pct: int, msg: str) -> None:
            logger.info("[discover] %s%% %s", pct, msg)
            if progress:
                progress(pct, msg)

        items: list[dict[str, Any]] = []
        summary: dict[str, int] = {}

        with self._client(ctx) as fmc:
            version = fmc.server_version()
            report(5, f"FMC version {version}")

            steps = len(OBJECT_KINDS) + 3
            done = 0

            for kind, entity_type in OBJECT_KINDS.items():
                done += 1
                report(int(done / steps * 90) + 5, f"reading {kind}")
                try:
                    records = fmc.list_objects(kind)
                except FmcError as exc:
                    logger.warning("skipping %s: %s", kind, exc)
                    continue
                summary[entity_type] = len(records)
                items.extend(self._as_items(entity_type, records))

            done += 1
            report(int(done / steps * 90) + 5, "reading managed devices")
            devices = fmc.list_devices()
            summary["device"] = len(devices)
            items.extend(self._as_items("device", devices))

            done += 1
            report(int(done / steps * 90) + 5, "reading access control policies")
            policies = fmc.list_access_policies()
            summary["access_policy"] = len(policies)
            items.extend(self._as_items("access_policy", policies))

            rules: list[dict[str, Any]] = []
            for policy in policies:
                try:
                    for rule in fmc.list_access_rules(policy["id"]):
                        rule["_policyName"] = policy.get("name")
                        rule["_policyId"] = policy.get("id")
                        rules.append(rule)
                except FmcError as exc:
                    logger.warning("could not read rules for policy %s: %s", policy.get("name"), exc)
            summary["access_rule"] = len(rules)
            items.extend(self._as_items("access_rule", rules))

            done += 1
            report(97, "reading NAT policies")
            try:
                nat = fmc.list_nat_policies()
                summary["nat_policy"] = len(nat)
                items.extend(self._as_items("nat_policy", nat))
            except FmcError as exc:
                logger.warning("could not read NAT policies: %s", exc)

        report(100, f"discovery complete: {len(items)} objects")
        return DiscoveryResult(product_version=version, items=items, summary=summary)

    @staticmethod
    def _as_items(entity_type: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "item_type": entity_type,
                "external_id": rec.get("id"),
                "name": rec.get("name"),
                "payload": rec,
            }
            for rec in records
        ]

    # -- dynamic Excel template -------------------------------------------
    def template_spec(self, discovery: DiscoveryResult | None = None) -> dict[str, list[str]]:
        spec: dict[str, list[str]] = {
            "Hosts": ["action", "name", "value", "description"],
            "Networks": ["action", "name", "value", "description"],
            "Ranges": ["action", "name", "value", "description"],
            "NetworkGroups": ["action", "name", "members", "description"],
            "Ports": ["action", "name", "protocol", "port", "description"],
            "AccessRules": [
                "action",
                "policy",
                "rule_name",
                "rule_action",
                "enabled",
                "source_networks",
                "destination_networks",
                "source_ports",
                "destination_ports",
                "applications",
                "urls",
                "log_begin",
                "log_end",
                "comment",
            ],
        }
        # Only surface sheets for object types this FMC actually exposes.
        if discovery and discovery.summary:
            present = discovery.summary
            if not present.get("range"):
                spec.pop("Ranges", None)
            if not present.get("port"):
                spec.pop("Ports", None)
        return spec

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _index(discovery: DiscoveryResult) -> dict[tuple[str, str], dict[str, Any]]:
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for item in discovery.items:
            name = item.get("name")
            if name:
                index[(item["item_type"], name.lower())] = item
        return index

    @staticmethod
    def _members(raw: Any) -> list[str]:
        return [part.strip() for part in str(raw or "").replace(";", ",").split(",") if part.strip()]

    @staticmethod
    def _unsupported_sheet_warnings(
        rows: dict[str, list[dict[str, Any]]],
    ) -> list[ValidationIssue]:
        """Say so loudly when a populated sheet is not deployable yet, instead of silently ignoring it."""
        issues: list[ValidationIssue] = []
        for sheet, records in rows.items():
            if sheet in SHEET_MAP:
                continue
            populated = sum(1 for r in records if str(r.get("action", "")).strip())
            if populated:
                issues.append(
                    ValidationIssue(
                        "warning",
                        sheet,
                        None,
                        None,
                        f"{populated} row(s) on '{sheet}' were ignored: this sheet is not deployable "
                        f"in {UNSUPPORTED_SHEETS.get(sheet, 'this release')}",
                    )
                )
        return issues

    # -- validation --------------------------------------------------------
    def validate(self, rows: dict[str, list[dict[str, Any]]], discovery: DiscoveryResult) -> ValidationResult:
        issues: list[ValidationIssue] = []
        existing = self._index(discovery)

        issues.extend(self._unsupported_sheet_warnings(rows))

        # Names this workbook will create, so groups may reference them.
        pending: set[tuple[str, str]] = set()
        for sheet, (entity, _kind, _type) in SHEET_MAP.items():
            for row in rows.get(sheet, []):
                if str(row.get("action", "")).strip().lower() == "create":
                    name = str(row.get("name", "")).strip()
                    if name:
                        pending.add((entity, name.lower()))

        for sheet, (entity, _kind, _type) in SHEET_MAP.items():
            seen: dict[str, int] = {}

            for index, row in enumerate(rows.get(sheet, []), start=2):
                action = str(row.get("action", "")).strip().lower()
                name = str(row.get("name", "")).strip()

                if not action:
                    continue
                if action not in VALID_ACTIONS:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "action", f"'{action}' is not create, update or delete"
                        )
                    )
                    continue
                if not name:
                    issues.append(ValidationIssue("error", sheet, index, "name", "name is required"))
                    continue

                if name.lower() in seen:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "name", f"duplicate of row {seen[name.lower()]}"
                        )
                    )
                seen.setdefault(name.lower(), index)

                key = (entity, name.lower())
                if action == "create" and key in existing:
                    issues.append(
                        ValidationIssue("error", sheet, index, "name", f"'{name}' already exists on the FMC")
                    )
                if action in {"update", "delete"} and key not in existing:
                    issues.append(
                        ValidationIssue("error", sheet, index, "name", f"'{name}' does not exist on the FMC")
                    )

                if action == "delete":
                    issues.extend(self._delete_warnings(sheet, index, name, entity, discovery))
                else:
                    issues.extend(self._validate_fields(sheet, index, row, existing, pending))

        return ValidationResult(issues=issues)

    def _validate_fields(
        self,
        sheet: str,
        index: int,
        row: dict[str, Any],
        existing: dict[tuple[str, str], dict[str, Any]],
        pending: set[tuple[str, str]],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        value = str(row.get("value", "")).strip()

        if sheet == "Hosts":
            if not value:
                issues.append(ValidationIssue("error", sheet, index, "value", "value is required"))
            else:
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "value", f"'{value}' is not a valid IP address"
                        )
                    )

        elif sheet == "Networks":
            if not value:
                issues.append(ValidationIssue("error", sheet, index, "value", "value is required"))
            elif "/" not in value:
                issues.append(
                    ValidationIssue("error", sheet, index, "value", "a prefix length is required, e.g. /24")
                )
            else:
                try:
                    ipaddress.ip_network(value, strict=True)
                except ValueError as exc:
                    severity = "warning" if "host bits set" in str(exc) else "error"
                    issues.append(
                        ValidationIssue(severity, sheet, index, "value", f"'{value}': {exc}")
                    )

        elif sheet == "Ranges":
            parts = value.split("-")
            if len(parts) != 2:
                issues.append(ValidationIssue("error", sheet, index, "value", "expected format 'start-end'"))
            else:
                try:
                    start, end = (ipaddress.ip_address(p.strip()) for p in parts)
                    if end < start:
                        issues.append(
                            ValidationIssue("error", sheet, index, "value", "end address is before start")
                        )
                except ValueError:
                    issues.append(
                        ValidationIssue("error", sheet, index, "value", f"'{value}' contains an invalid IP")
                    )

        elif sheet == "Ports":
            protocol = str(row.get("protocol", "")).strip().upper()
            port = str(row.get("port", "")).strip()
            if protocol not in {"TCP", "UDP"}:
                issues.append(
                    ValidationIssue("error", sheet, index, "protocol", "protocol must be TCP or UDP")
                )
            if not self._is_valid_port(port):
                issues.append(
                    ValidationIssue("error", sheet, index, "port", f"'{port}' is not a valid port or range")
                )

        elif sheet == "NetworkGroups":
            members = self._members(row.get("members"))
            if not members:
                issues.append(
                    ValidationIssue("error", sheet, index, "members", "at least one member is required")
                )
            for member in members:
                key = member.lower()
                known = any(
                    (entity, key) in existing or (entity, key) in pending
                    for entity in GROUP_MEMBER_ENTITIES
                )
                if not known:
                    issues.append(
                        ValidationIssue("error", sheet, index, "members", f"member '{member}' does not exist")
                    )
        return issues

    @staticmethod
    def _is_valid_port(port: str) -> bool:
        if not port:
            return False
        parts = port.split("-")
        if len(parts) > 2:
            return False
        try:
            numbers = [int(p) for p in parts]
        except ValueError:
            return False
        if not all(1 <= n <= 65535 for n in numbers):
            return False
        return len(numbers) == 1 or numbers[0] <= numbers[1]

    @staticmethod
    def _delete_warnings(
        sheet: str, index: int, name: str, entity: str, discovery: DiscoveryResult
    ) -> list[ValidationIssue]:
        """Warn when deleting an object that a network group still references."""
        if entity not in {"host", "network", "range"}:
            return []
        for item in discovery.items:
            if item["item_type"] != "network_group":
                continue
            for member in item["payload"].get("objects") or []:
                if str(member.get("name", "")).lower() == name.lower():
                    return [
                        ValidationIssue(
                            "warning",
                            sheet,
                            index,
                            "name",
                            f"'{name}' is still a member of group '{item.get('name')}'",
                        )
                    ]
        return []

    # -- planning ----------------------------------------------------------
    def plan(self, rows: dict[str, list[dict[str, Any]]], discovery: DiscoveryResult) -> ChangePlan:
        existing = self._index(discovery)
        change = ChangePlan()

        for sheet in APPLY_ORDER:
            entity, kind, fmc_type = SHEET_MAP[sheet]

            for row in rows.get(sheet, []):
                action = str(row.get("action", "")).strip().lower()
                name = str(row.get("name", "")).strip()
                if action not in VALID_ACTIONS or not name:
                    continue

                current = existing.get((entity, name.lower()))
                entry: dict[str, Any] = {
                    "sheet": sheet,
                    "kind": kind,
                    "entity": entity,
                    "name": name,
                    "action": action,
                }

                if action == "delete":
                    if not current:
                        continue
                    entry["id"] = current.get("external_id")
                    entry["before"] = current.get("payload")
                    change.deletes.append(entry)
                    continue

                entry["payload"] = self._build_payload(sheet, fmc_type, row, existing)
                if action == "create":
                    change.creates.append(entry)
                elif current:
                    entry["id"] = current.get("external_id")
                    entry["before"] = current.get("payload")
                    change.updates.append(entry)

        change.deletes.reverse()  # groups are removed before their members
        return change

    def _build_payload(
        self,
        sheet: str,
        fmc_type: str,
        row: dict[str, Any],
        existing: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": str(row.get("name", "")).strip(), "type": fmc_type}
        description = str(row.get("description", "") or "").strip()
        if description:
            payload["description"] = description

        if sheet == "Ports":
            payload["protocol"] = str(row.get("protocol", "")).strip().upper()
            payload["port"] = str(row.get("port", "")).strip()
        elif sheet == "NetworkGroups":
            objects: list[dict[str, Any]] = []
            literals: list[dict[str, Any]] = []
            for member in self._members(row.get("members")):
                resolved = next(
                    (
                        existing[(entity, member.lower())]
                        for entity in GROUP_MEMBER_ENTITIES
                        if (entity, member.lower()) in existing
                    ),
                    None,
                )
                if resolved:
                    objects.append(
                        {
                            "id": resolved.get("external_id"),
                            "type": resolved["payload"].get("type", "Network"),
                            "name": resolved.get("name"),
                        }
                    )
                else:
                    # Created earlier in this same run; FMC resolves it by name at apply time.
                    literals.append({"type": "Network", "value": member})
            if objects:
                payload["objects"] = objects
            if literals:
                payload["literals"] = literals
        else:
            payload["value"] = str(row.get("value", "")).strip()

        return payload

    # -- deployment --------------------------------------------------------
    def deploy(
        self,
        ctx: ConnectionContext,
        plan: ChangePlan,
        engine: str = "rest",
        dry_run: bool = True,
        progress: ProgressCallback | None = None,
    ) -> DeploymentResult:
        if engine not in self.manifest.engines:
            raise ValueError(f"engine '{engine}' not supported by {self.manifest.key}")
        if engine != "rest":
            raise NotImplementedError(f"the '{engine}' engine is not implemented yet; use 'rest'")

        operations = plan.creates + plan.updates + plan.deletes
        total = max(len(operations), 1)

        if dry_run:
            return DeploymentResult(
                ok=True,
                applied=0,
                failed=0,
                details=[{**entry, "status": "planned"} for entry in operations],
            )

        details: list[dict[str, Any]] = []
        applied = failed = 0

        with self._client(ctx) as fmc:
            for position, entry in enumerate(operations, start=1):
                action, kind = entry["action"], entry["kind"]
                try:
                    if action == "create":
                        created = fmc.create_object(kind, entry["payload"])
                        details.append(
                            {
                                **entry,
                                "status": "created",
                                "id": created.get("id"),
                                "undo": {"action": "delete", "kind": kind, "id": created.get("id")},
                            }
                        )
                    elif action == "update":
                        fmc.update_object(kind, entry["id"], entry["payload"])
                        details.append(
                            {
                                **entry,
                                "status": "updated",
                                "undo": {
                                    "action": "update",
                                    "kind": kind,
                                    "id": entry["id"],
                                    "payload": entry.get("before"),
                                },
                            }
                        )
                    else:
                        fmc.delete_object(kind, entry["id"])
                        details.append(
                            {
                                **entry,
                                "status": "deleted",
                                "undo": {"action": "create", "kind": kind, "payload": entry.get("before")},
                            }
                        )
                    applied += 1
                except FmcError as exc:
                    failed += 1
                    details.append({**entry, "status": "failed", "error": str(exc)})
                    logger.warning("%s %s failed: %s", action, entry.get("name"), exc)

                if progress:
                    progress(int(position / total * 100), f"{position}/{len(operations)} applied")

        return DeploymentResult(ok=failed == 0, applied=applied, failed=failed, details=details)

    # -- rollback ----------------------------------------------------------
    def rollback(self, ctx: ConnectionContext, result: DeploymentResult) -> DeploymentResult:
        """Undo a deployment in reverse order using the undo record kept per operation."""
        undoable = [d for d in reversed(result.details) if d.get("undo")]
        details: list[dict[str, Any]] = []
        applied = failed = 0

        with self._client(ctx) as fmc:
            for entry in undoable:
                undo = entry["undo"]
                try:
                    if undo["action"] == "delete":
                        fmc.delete_object(undo["kind"], undo["id"])
                    elif undo["action"] == "update":
                        fmc.update_object(undo["kind"], undo["id"], undo["payload"])
                    else:
                        payload = {k: v for k, v in (undo.get("payload") or {}).items() if k != "id"}
                        fmc.create_object(undo["kind"], payload)
                    applied += 1
                    details.append({"name": entry.get("name"), "status": "reverted"})
                except FmcError as exc:
                    failed += 1
                    details.append({"name": entry.get("name"), "status": "failed", "error": str(exc)})

        return DeploymentResult(ok=failed == 0, applied=applied, failed=failed, details=details)

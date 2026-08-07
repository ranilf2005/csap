"""Cisco Secure Firewall (FMC) plugin - the reference implementation of SecurityPlugin."""

from __future__ import annotations

import ipaddress
import json
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

# Plain objects must exist before groups can reference them, and rules come last.
APPLY_ORDER = ["Hosts", "Networks", "Ranges", "Ports", "NetworkGroups", "AccessRules"]

ACCESS_RULE_SHEET = "AccessRules"
ACCESS_RULE_ACTIONS = {
    "ALLOW", "TRUST", "BLOCK", "MONITOR",
    "BLOCK_RESET", "BLOCK_INTERACTIVE", "BLOCK_RESET_INTERACTIVE",
}
NETWORK_COLUMNS = ("source_networks", "destination_networks")
PORT_COLUMNS = ("source_ports", "destination_ports")

VALID_ACTIONS = {"create", "update", "delete"}
GROUP_MEMBER_ENTITIES = ("host", "network", "range", "network_group")
PORT_ENTITIES = ("port", "port_group")
URL_ENTITIES = ("url", "url_group")

# Sheets the template offers for reference but that cannot be deployed yet.
UNSUPPORTED_SHEETS = {"NatRules": "a future release"}

# Entities whose workbook row is just name + a single value field.
VALUE_OBJECT_SHEETS = {"host": "Hosts", "network": "Networks", "range": "Ranges"}

# Fields compared against the device to spot a row edited without setting an action.
COMPARE_FIELDS = {
    "Hosts": ["value", "description"],
    "Networks": ["value", "description"],
    "Ranges": ["value", "description"],
    "Ports": ["protocol", "port", "description"],
    "NetworkGroups": ["members", "description"],
}


def _split(raw: Any) -> list[str]:
    return [p.strip() for p in str(raw or "").replace(";", ",").split(",") if p.strip()]


def _is_literal(value: str) -> bool:
    """An address typed straight into a rule cell rather than referencing an object."""
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return True


# sheet -> column -> (required, what it is, example). Drives the header notes,
# the required/optional colouring and the Field Guide sheet.
_ACTION = ("required", "create, update or delete. Leave blank to ignore the row.", "create")
_NAME = ("required", "Object name. Must be unique within the sheet.", "APP01")
_DESC = ("optional", "Free text description.", "Application server")

FIELD_GUIDE: dict[str, dict[str, tuple[str, str, str]]] = {
    "Hosts": {
        "action": _ACTION,
        "name": _NAME,
        "value": ("required", "One IP address. No prefix. Use Networks for subnets.", "10.1.1.30"),
        "description": _DESC,
    },
    "Networks": {
        "action": _ACTION,
        "name": _NAME,
        "value": ("required", "Subnet in CIDR form. The prefix length is required.", "10.2.0.0/24"),
        "description": _DESC,
    },
    "Ranges": {
        "action": _ACTION,
        "name": _NAME,
        "value": ("required", "Start and end address separated by a hyphen.", "10.1.1.10-10.1.1.50"),
        "description": _DESC,
    },
    "Ports": {
        "action": _ACTION,
        "name": _NAME,
        "protocol": ("required", "TCP or UDP.", "TCP"),
        "port": ("required", "1-65535, or a range such as 8080-8090.", "8080"),
        "description": _DESC,
    },
    "NetworkGroups": {
        "action": _ACTION,
        "name": _NAME,
        "members": (
            "required",
            "Object names separated by commas. On update, list EVERY member you want "
            "the group to end up with - omitted members are removed.",
            "WEB01, WEB02, DMZ-NET",
        ),
        "description": _DESC,
    },
    "AccessRules": {
        "action": _ACTION,
        "policy": ("required", "Name of an existing access control policy on the FMC.", "Corp-ACP"),
        "rule_name": ("required", "Rule name. Must be unique within the policy.", "allow-web"),
        "rule_action": (
            "required",
            "One of: " + ", ".join(sorted(ACCESS_RULE_ACTIONS)),
            "ALLOW",
        ),
        "enabled": ("optional", "true or false. Defaults to true.", "true"),
        "source_networks": (
            "optional",
            "Object names or literal addresses, comma separated. Blank means any.",
            "DMZ, 10.1.1.0/24",
        ),
        "destination_networks": (
            "optional",
            "Object names or literal addresses, comma separated. Blank means any.",
            "WEB01",
        ),
        "source_ports": ("optional", "Port object names, comma separated. Blank means any.", ""),
        "destination_ports": (
            "optional",
            "Port object names, comma separated. Blank means any.",
            "HTTPS",
        ),
        "applications": (
            "not supported",
            "Shown for reference. CSAP cannot set applications yet; this column is ignored.",
            "",
        ),
        "urls": ("optional", "URL object names, or literal URLs.", "BLOCKED-SITES"),
        "log_begin": ("optional", "true or false. Log at the start of the connection.", "false"),
        "log_end": ("optional", "true or false. Log at the end of the connection.", "true"),
        "send_events_to_fmc": (
            "conditional",
            "Required to be true when log_begin or log_end is true - the FMC rejects a rule "
            "that logs with no destination. Defaults to true when logging is on.",
            "true",
        ),
        "comment": ("optional", "Comment added to the rule history.", "Change CHG0012345"),
    },
}


class SecureFirewallPlugin(SecurityPlugin):
    manifest = PluginManifest(
        key="secure_firewall",
        display_name="Cisco Secure Firewall (FMC)",
        description="Discovery, validation and deployment against Firewall Management Center.",
        engines=("rest", "ansible", "terraform"),
        entity_types=(*OBJECT_KINDS.values(), "device", "access_policy", "access_rule", "nat_policy"),
        min_product_version="6.7",
    )

    reference_sheets = frozenset(UNSUPPORTED_SHEETS)

    def field_guide(self) -> dict[str, dict[str, tuple[str, str, str]]]:
        return FIELD_GUIDE

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

                nat_rules: list[dict[str, Any]] = []
                for policy in nat:
                    try:
                        for rule in fmc.list_nat_rules(policy["id"]):
                            rule["_policyName"] = policy.get("name")
                            rule["_policyId"] = policy.get("id")
                            nat_rules.append(rule)
                    except FmcError as exc:
                        logger.warning("could not read NAT rules for %s: %s", policy.get("name"), exc)
                summary["nat_rule"] = len(nat_rules)
                items.extend(self._as_items("nat_rule", nat_rules))
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
        # Every deployable sheet is always present: an empty category still needs a
        # place to add the first object.
        return {
            "Hosts": ["action", "name", "value", "description"],
            "Networks": ["action", "name", "value", "description"],
            "Ranges": ["action", "name", "value", "description"],
            "Ports": ["action", "name", "protocol", "port", "description"],
            "NetworkGroups": ["action", "name", "members", "description"],
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
                "send_events_to_fmc",
                "comment",
            ],
            "NatRules": [
                "action",
                "policy",
                "rule_name",
                "nat_type",
                "source_interface",
                "destination_interface",
                "original_source",
                "translated_source",
                "original_destination",
                "translated_destination",
                "enabled",
            ],
        }

    # -- current configuration as rows -------------------------------------
    @staticmethod
    def _names(container: Any, literal_key: str = "value") -> str:
        """Flatten an FMC {objects:[...], literals:[...]} container into a readable list."""
        if not isinstance(container, dict):
            return ""
        parts = [str(o.get("name", "")) for o in container.get("objects") or []]
        parts += [
            str(lit.get(literal_key) or lit.get("value") or "")
            for lit in container.get("literals") or []
        ]
        return ", ".join(p for p in parts if p)

    @staticmethod
    def _name_of(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or value.get("value") or "")
        if isinstance(value, list):
            return ", ".join(str(v.get("name") or v.get("value") or "") for v in value if isinstance(v, dict))
        return ""

    def _row_for_item(self, item: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Render one discovered object as the workbook row that represents it."""
        entity = item.get("item_type")
        payload = item.get("payload") or {}
        name = item.get("name") or ""
        description = payload.get("description", "") or ""

        if entity in VALUE_OBJECT_SHEETS:
            return VALUE_OBJECT_SHEETS[entity], {
                "action": "",
                "name": name,
                "value": payload.get("value", ""),
                "description": description,
            }
        if entity == "port":
            return "Ports", {
                "action": "",
                "name": name,
                "protocol": payload.get("protocol", ""),
                "port": payload.get("port", ""),
                "description": description,
            }
        if entity == "network_group":
            return "NetworkGroups", {
                "action": "",
                "name": name,
                "members": self._names(payload),
                "description": description,
            }
        if entity == "access_rule":
            applications = (payload.get("applications") or {}).get("applications") or []
            return "AccessRules", {
                "action": "",
                "policy": payload.get("_policyName", ""),
                "rule_name": name,
                "rule_action": payload.get("action", ""),
                "enabled": payload.get("enabled", ""),
                "source_networks": self._names(payload.get("sourceNetworks")),
                "destination_networks": self._names(payload.get("destinationNetworks")),
                "source_ports": self._names(payload.get("sourcePorts")),
                "destination_ports": self._names(payload.get("destinationPorts")),
                "applications": ", ".join(str(a.get("name", "")) for a in applications),
                "urls": self._names(payload.get("urls"), literal_key="url"),
                "log_begin": payload.get("logBegin", ""),
                "log_end": payload.get("logEnd", ""),
                "comment": "",
            }
        if entity == "nat_rule":
            return "NatRules", {
                "action": "",
                "policy": payload.get("_policyName", ""),
                "rule_name": name or payload.get("id", ""),
                "nat_type": payload.get("natType", "") or payload.get("type", ""),
                "source_interface": self._name_of(payload.get("sourceInterface")),
                "destination_interface": self._name_of(payload.get("destinationInterface")),
                "original_source": self._name_of(payload.get("originalSource")),
                "translated_source": self._name_of(payload.get("translatedSource")),
                "original_destination": self._name_of(payload.get("originalDestination")),
                "translated_destination": self._name_of(payload.get("translatedDestination")),
                "enabled": payload.get("enabled", ""),
            }
        return None

    def existing_rows(self, discovery: DiscoveryResult) -> dict[str, list[dict[str, Any]]]:
        rows: dict[str, list[dict[str, Any]]] = {sheet: [] for sheet in self.template_spec()}
        for item in discovery.items:
            mapped = self._row_for_item(item)
            if mapped:
                sheet, row = mapped
                rows[sheet].append(row)
        return rows

    def _device_rows(self, discovery: DiscoveryResult) -> dict[tuple[str, str], dict[str, Any]]:
        """Sheet + lowercase name -> the row that represents the object as it is today."""
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for item in discovery.items:
            mapped = self._row_for_item(item)
            if not mapped:
                continue
            sheet, row = mapped
            key_name = str(row.get("name") or row.get("rule_name") or "").strip().lower()
            if key_name:
                index[(sheet, key_name)] = row
        return index

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
                planned = UNSUPPORTED_SHEETS.get(sheet, "a future release")
                issues.append(
                    ValidationIssue(
                        "warning",
                        sheet,
                        None,
                        None,
                        f"'{sheet}' is reference only in this release, so {populated} row(s) with an "
                        "action were ignored. Nothing on this sheet will be deployed.",
                        f"No action needed for the rest of the workbook to deploy. Make these "
                        f"changes directly in FMC for now; automation is planned for {planned}.",
                    )
                )
        return issues

    # -- validation --------------------------------------------------------
    def validate(self, rows: dict[str, list[dict[str, Any]]], discovery: DiscoveryResult) -> ValidationResult:
        issues: list[ValidationIssue] = []
        existing = self._index(discovery)
        device_rows = self._device_rows(discovery)

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

                # Two rows naming the same object is always wrong, action or not.
                if name:
                    if name.lower() in seen:
                        issues.append(
                            ValidationIssue(
                                "error", sheet, index, "name",
                                f"duplicate of row {seen[name.lower()]}",
                                f"Delete this row or row {seen[name.lower()]}, or rename one of them. "
                                "Each object may appear only once per sheet.",
                            )
                        )
                    seen.setdefault(name.lower(), index)

                if not action:
                    issues.extend(
                        self._blank_action_warnings(
                            sheet, index, row, name, device_rows.get((sheet, name.lower()))
                        )
                    )
                    continue

                if action not in VALID_ACTIONS:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "action",
                            f"'{action}' is not create, update or delete",
                            "Set the action cell to create, update or delete. "
                            "Leave it empty to ignore the row.",
                        )
                    )
                    continue
                if not name:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "name", "name is required",
                            "Enter the object name, or clear the action cell to ignore this row.",
                        )
                    )
                    continue

                key = (entity, name.lower())
                if action == "create" and key in existing:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "name",
                            f"'{name}' already exists on the FMC",
                            "Change action to update to modify the existing object, "
                            "or choose a different name to create a new one.",
                        )
                    )
                if action in {"update", "delete"} and key not in existing:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "name",
                            f"'{name}' does not exist on the FMC",
                            "Check the spelling against the exported configuration, "
                            "or change action to create to add it.",
                        )
                    )

                if action == "delete":
                    issues.extend(self._delete_warnings(sheet, index, name, entity, discovery))
                else:
                    issues.extend(self._validate_fields(sheet, index, row, existing, pending))

        issues.extend(self._validate_access_rules(rows, discovery, existing, pending))
        return ValidationResult(issues=issues)

    # -- access rules ------------------------------------------------------
    @staticmethod
    def _policies(discovery: DiscoveryResult) -> dict[str, dict[str, Any]]:
        return {
            (item.get("name") or "").lower(): item
            for item in discovery.items
            if item["item_type"] == "access_policy" and item.get("name")
        }

    @staticmethod
    def _rules(discovery: DiscoveryResult) -> dict[tuple[str, str], dict[str, Any]]:
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for item in discovery.items:
            if item["item_type"] != "access_rule" or not item.get("name"):
                continue
            policy = str((item["payload"] or {}).get("_policyName") or "").lower()
            index[(policy, item["name"].lower())] = item
        return index

    def _validate_access_rules(
        self,
        rows: dict[str, list[dict[str, Any]]],
        discovery: DiscoveryResult,
        existing: dict[tuple[str, str], dict[str, Any]],
        pending: set[tuple[str, str]],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        policies = self._policies(discovery)
        rules = self._rules(discovery)
        seen: dict[tuple[str, str], int] = {}
        sheet = ACCESS_RULE_SHEET

        for index, row in enumerate(rows.get(sheet, []), start=2):
            action = str(row.get("action", "")).strip().lower()
            policy = str(row.get("policy", "")).strip()
            name = str(row.get("rule_name", "")).strip()

            if not action:
                continue
            if action not in VALID_ACTIONS:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "action",
                        f"'{action}' is not create, update or delete",
                        "Pick create, update or delete from the dropdown, or clear the cell.",
                    )
                )
                continue
            if not name:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "rule_name", "rule_name is required",
                        "Enter the rule name exactly as it appears in the access control policy.",
                    )
                )
                continue
            if not policy:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "policy", "policy is required",
                        "Enter the access control policy name, for example "
                        f"'{next(iter(policies.values()), {}).get('name', 'Corp-ACP')}'.",
                    )
                )
                continue
            if policy.lower() not in policies:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "policy",
                        f"access control policy '{policy}' does not exist on the FMC",
                        "Use one of: " + ", ".join(sorted(p["name"] for p in policies.values()))
                        if policies else "No access control policies were discovered.",
                    )
                )
                continue

            key = (policy.lower(), name.lower())
            if key in seen:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "rule_name",
                        f"duplicate of row {seen[key]} in policy '{policy}'",
                        f"Delete this row or row {seen[key]}. A rule name appears once per policy.",
                    )
                )
            seen.setdefault(key, index)

            if action == "create" and key in rules:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "rule_name",
                        f"rule '{name}' already exists in policy '{policy}'",
                        "Change action to update to modify it, or rename the new rule.",
                    )
                )
            if action in {"update", "delete"} and key not in rules:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "rule_name",
                        f"rule '{name}' does not exist in policy '{policy}'",
                        "Check the spelling against the exported configuration, "
                        "or use create to add it.",
                    )
                )

            if action == "delete":
                continue

            rule_action = str(row.get("rule_action", "")).strip().upper()
            if rule_action not in ACCESS_RULE_ACTIONS:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "rule_action",
                        f"'{row.get('rule_action', '')}' is not a valid rule action",
                        "Use one of: " + ", ".join(sorted(ACCESS_RULE_ACTIONS)),
                    )
                )

            # The FMC refuses a rule that logs with nowhere to send the events.
            logging_on = self._as_bool(row.get("log_begin")) or self._as_bool(row.get("log_end"))
            if logging_on and not self._as_bool(row.get("send_events_to_fmc"), default=True):
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "send_events_to_fmc",
                        "logging is enabled but no destination is set, which the FMC rejects",
                        "Set send_events_to_fmc to true, or set log_begin and log_end to false.",
                    )
                )

            if _split(row.get("applications")):
                issues.append(
                    ValidationIssue(
                        "warning", sheet, index, "applications",
                        "applications cannot be set by CSAP yet, so this column is ignored",
                        "Leave it as exported. Set applications on this rule in FMC directly "
                        "if you need them.",
                    )
                )

            issues.extend(self._validate_rule_members(sheet, index, row, existing, pending))

        return issues

    def _validate_rule_members(
        self,
        sheet: str,
        index: int,
        row: dict[str, Any],
        existing: dict[tuple[str, str], dict[str, Any]],
        pending: set[tuple[str, str]],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        for column in NETWORK_COLUMNS:
            for member in _split(row.get(column)):
                if _is_literal(member):
                    continue
                known = any(
                    (e, member.lower()) in existing or (e, member.lower()) in pending
                    for e in GROUP_MEMBER_ENTITIES
                )
                if not known:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, column,
                            f"'{member}' is not a known network object",
                            f"Correct the spelling, add a create row for '{member}' on the Hosts "
                            "or Networks sheet, or type a literal address such as 10.1.1.0/24.",
                        )
                    )

        for column in PORT_COLUMNS:
            for member in _split(row.get(column)):
                known = any(
                    (e, member.lower()) in existing or (e, member.lower()) in pending
                    for e in PORT_ENTITIES
                )
                if not known:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, column,
                            f"'{member}' is not a known port object",
                            f"Correct the spelling, or add a create row for '{member}' "
                            "on the Ports sheet.",
                        )
                    )
        return issues

    @staticmethod
    def _normalise(sheet: str, field: str, value: Any) -> str:
        text = str(value if value is not None else "").strip()
        if field == "members":
            parts = sorted(p.strip().lower() for p in text.replace(";", ",").split(",") if p.strip())
            return ",".join(parts)
        return text.lower()

    def _blank_action_warnings(
        self, sheet: str, index: int, row: dict[str, Any], name: str, device_row: dict[str, Any] | None
    ) -> list[ValidationIssue]:
        """A row with no action is ignored. Say so when the row clearly meant to change something."""
        fields = COMPARE_FIELDS.get(sheet, [])
        if not name or not fields:
            return []

        if device_row is None:
            if any(str(row.get(f, "") or "").strip() for f in fields):
                return [
                    ValidationIssue(
                        "warning", sheet, index, "action",
                        f"'{name}' is not on the FMC and 'action' is blank, so this row is ignored.",
                        f"Type create in the action cell of row {index} to add this object, "
                        "then upload the workbook again.",
                    )
                ]
            return []

        changed = [
            f for f in fields
            if self._normalise(sheet, f, row.get(f)) != self._normalise(sheet, f, device_row.get(f))
        ]
        if changed:
            return [
                ValidationIssue(
                    "warning", sheet, index, "action",
                    f"'{name}' differs from the FMC ({', '.join(changed)}) but 'action' is blank, "
                    "so this row is ignored.",
                    f"Type update in the action cell of row {index} to apply your edit, "
                    f"or restore the original value to leave it unchanged.",
                )
            ]
        return []

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
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "value", "value is required",
                        "Enter a single IP address, for example 10.1.1.20.",
                    )
                )
            else:
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "value", f"'{value}' is not a valid IP address",
                            "Enter one IPv4 or IPv6 address with no prefix, for example 10.1.1.20. "
                            "Use the Networks sheet for subnets.",
                        )
                    )

        elif sheet == "Networks":
            if not value:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "value", "value is required",
                        "Enter a subnet in CIDR form, for example 10.2.0.0/24.",
                    )
                )
            elif "/" not in value:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "value", "a prefix length is required, e.g. /24",
                        f"Change '{value}' to include a prefix, for example '{value}/24'. "
                        "Use the Hosts sheet for a single address.",
                    )
                )
            else:
                try:
                    ipaddress.ip_network(value, strict=True)
                except ValueError as exc:
                    host_bits = "host bits set" in str(exc)
                    network = ""
                    if host_bits:
                        network = str(ipaddress.ip_network(value, strict=False))
                    issues.append(
                        ValidationIssue(
                            "warning" if host_bits else "error",
                            sheet, index, "value", f"'{value}': {exc}",
                            f"Use the network address '{network}' instead." if host_bits
                            else "Enter a valid subnet in CIDR form, for example 10.2.0.0/24.",
                        )
                    )

        elif sheet == "Ranges":
            parts = value.split("-")
            if len(parts) != 2:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "value", "expected format 'start-end'",
                        "Enter two addresses separated by a hyphen, for example "
                        "10.1.1.10-10.1.1.50.",
                    )
                )
            else:
                try:
                    start, end = (ipaddress.ip_address(p.strip()) for p in parts)
                    if end < start:
                        issues.append(
                            ValidationIssue(
                                "error", sheet, index, "value", "end address is before start",
                                f"Swap them so the range reads '{end}-{start}'.",
                            )
                        )
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "value", f"'{value}' contains an invalid IP",
                            "Check both addresses, for example 10.1.1.10-10.1.1.50.",
                        )
                    )

        elif sheet == "Ports":
            protocol = str(row.get("protocol", "")).strip().upper()
            port = str(row.get("port", "")).strip()
            if protocol not in {"TCP", "UDP"}:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "protocol", "protocol must be TCP or UDP",
                        "Set the protocol cell to TCP or UDP.",
                    )
                )
            if not self._is_valid_port(port):
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "port", f"'{port}' is not a valid port or range",
                        "Enter a number from 1 to 65535, or a range such as 8080-8090.",
                    )
                )

        elif sheet == "NetworkGroups":
            members = self._members(row.get("members"))
            if not members:
                issues.append(
                    ValidationIssue(
                        "error", sheet, index, "members", "at least one member is required",
                        "List the member object names separated by commas, "
                        "for example 'WEB01, WEB02, DMZ-NET'.",
                    )
                )
            for member in members:
                key = member.lower()
                known = any(
                    (entity, key) in existing or (entity, key) in pending
                    for entity in GROUP_MEMBER_ENTITIES
                )
                if not known:
                    issues.append(
                        ValidationIssue(
                            "error", sheet, index, "members", f"member '{member}' does not exist",
                            f"Correct the spelling of '{member}', or add a row with action=create "
                            "for it on the Hosts, Networks or Ranges sheet.",
                        )
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
                            f"Remove '{name}' from '{item.get('name')}' on the NetworkGroups sheet "
                            "in the same upload, otherwise the FMC will reject the delete.",
                        )
                    ]
        return []

    # -- planning ----------------------------------------------------------
    def plan(self, rows: dict[str, list[dict[str, Any]]], discovery: DiscoveryResult) -> ChangePlan:
        existing = self._index(discovery)
        change = ChangePlan()

        for sheet in APPLY_ORDER:
            if sheet == ACCESS_RULE_SHEET:
                self._plan_access_rules(rows, discovery, existing, change)
                continue

            entity, kind, fmc_type = SHEET_MAP[sheet]

            for row in rows.get(sheet, []):
                action = str(row.get("action", "")).strip().lower()
                name = str(row.get("name", "")).strip()
                if action not in VALID_ACTIONS or not name:
                    continue

                current = existing.get((entity, name.lower()))
                entry: dict[str, Any] = {
                    "target": "object",
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

        change.deletes.reverse()  # rules and groups go before the objects they reference
        return change

    def _plan_access_rules(
        self,
        rows: dict[str, list[dict[str, Any]]],
        discovery: DiscoveryResult,
        existing: dict[tuple[str, str], dict[str, Any]],
        change: ChangePlan,
    ) -> None:
        policies = self._policies(discovery)
        rules = self._rules(discovery)

        for row in rows.get(ACCESS_RULE_SHEET, []):
            action = str(row.get("action", "")).strip().lower()
            policy = str(row.get("policy", "")).strip()
            name = str(row.get("rule_name", "")).strip()
            if action not in VALID_ACTIONS or not name or policy.lower() not in policies:
                continue

            policy_item = policies[policy.lower()]
            current = rules.get((policy.lower(), name.lower()))
            entry: dict[str, Any] = {
                "target": "access_rule",
                "sheet": ACCESS_RULE_SHEET,
                "entity": "access_rule",
                "kind": "accessrules",
                "name": name,
                "policy": policy,
                "policy_id": policy_item.get("external_id"),
                "action": action,
            }

            if action == "delete":
                if not current:
                    continue
                entry["id"] = current.get("external_id")
                entry["before"] = current.get("payload")
                change.deletes.append(entry)
                continue

            entry["payload"] = self._build_rule_payload(row, existing)
            if action == "create":
                change.creates.append(entry)
            elif current:
                entry["id"] = current.get("external_id")
                entry["before"] = current.get("payload")
                change.updates.append(entry)

    def _build_rule_payload(
        self, row: dict[str, Any], existing: dict[tuple[str, str], dict[str, Any]]
    ) -> dict[str, Any]:
        log_begin = self._as_bool(row.get("log_begin"))
        log_end = self._as_bool(row.get("log_end"))

        payload: dict[str, Any] = {
            "name": str(row.get("rule_name", "")).strip(),
            "type": "AccessRule",
            "action": str(row.get("rule_action", "ALLOW")).strip().upper() or "ALLOW",
            "enabled": self._as_bool(row.get("enabled"), default=True),
            "logBegin": log_begin,
            "logEnd": log_end,
        }

        # FMC rejects a rule that logs with nowhere to send the events.
        if log_begin or log_end:
            payload["sendEventsToFMC"] = self._as_bool(
                row.get("send_events_to_fmc"), default=True
            )

        for column, key in zip(NETWORK_COLUMNS, ("sourceNetworks", "destinationNetworks"), strict=True):
            container = self._network_container(_split(row.get(column)), existing)
            if container:
                payload[key] = container

        for column, key in zip(PORT_COLUMNS, ("sourcePorts", "destinationPorts"), strict=True):
            container = self._port_container(_split(row.get(column)), existing)
            if container:
                payload[key] = container

        urls = self._url_container(_split(row.get("urls")), existing)
        if urls:
            payload["urls"] = urls

        comment = str(row.get("comment", "") or "").strip()
        if comment:
            payload["newComments"] = [comment]
        return payload

    @staticmethod
    def _url_container(
        names: list[str], existing: dict[tuple[str, str], dict[str, Any]]
    ) -> dict[str, Any]:
        objects, literals = [], []
        for member in names:
            resolved = next(
                (
                    existing[(entity, member.lower())]
                    for entity in URL_ENTITIES
                    if (entity, member.lower()) in existing
                ),
                None,
            )
            if resolved:
                objects.append(
                    {
                        "id": resolved.get("external_id"),
                        "type": resolved["payload"].get("type", "Url"),
                        "name": resolved.get("name"),
                    }
                )
            else:
                literals.append({"type": "Url", "url": member})
        container: dict[str, Any] = {}
        if objects:
            container["objects"] = objects
        if literals:
            container["literals"] = literals
        return container

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        text = str(value if value is not None else "").strip().lower()
        if text in {"true", "yes", "1", "y"}:
            return True
        if text in {"false", "no", "0", "n"}:
            return False
        return default

    @staticmethod
    def _network_container(
        names: list[str], existing: dict[tuple[str, str], dict[str, Any]]
    ) -> dict[str, Any]:
        objects, literals = [], []
        for member in names:
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
            elif _is_literal(member):
                literals.append(
                    {"type": "Host" if "/" not in member else "Network", "value": member}
                )
        container: dict[str, Any] = {}
        if objects:
            container["objects"] = objects
        if literals:
            container["literals"] = literals
        return container

    @staticmethod
    def _port_container(
        names: list[str], existing: dict[tuple[str, str], dict[str, Any]]
    ) -> dict[str, Any]:
        objects = []
        for member in names:
            resolved = next(
                (
                    existing[(entity, member.lower())]
                    for entity in PORT_ENTITIES
                    if (entity, member.lower()) in existing
                ),
                None,
            )
            if resolved:
                objects.append(
                    {
                        "id": resolved.get("external_id"),
                        "type": resolved["payload"].get("type", "ProtocolPortObject"),
                        "name": resolved.get("name"),
                    }
                )
        return {"objects": objects} if objects else {}

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
    @staticmethod
    def _endpoint(entry: dict[str, Any]) -> tuple[str, str]:
        """(method, path) for one planned operation, relative to the config API root."""
        if entry.get("target") == "access_rule":
            base = f"policy/accesspolicies/{entry.get('policy_id', '')}/accessrules"
        else:
            base = f"object/{entry['kind']}"

        if entry["action"] == "create":
            return "POST", base
        return ("PUT" if entry["action"] == "update" else "DELETE", f"{base}/{entry.get('id', '')}")

    def preview(self, plan: ChangePlan, host: str | None = None) -> list[dict[str, Any]]:
        """Render the plan as the exact calls it will make, so nothing is applied blind."""
        target = host or "<fmc>"
        root = f"https://{target}/api/fmc_config/v1/domain/{{domainUUID}}"
        calls: list[dict[str, Any]] = []

        for entry in plan.creates + plan.updates + plan.deletes:
            method, suffix = self._endpoint(entry)
            url = f"{root}/{suffix}"
            body: dict[str, Any] | None = None
            if entry["action"] == "create":
                body = entry.get("payload")
            elif entry["action"] == "update":
                body = {**(entry.get("payload") or {}), "id": entry.get("id", "")}

            command = [
                f"curl -k -X {method} \\",
                f"  '{url}' \\",
                "  -H 'Content-Type: application/json' \\",
                "  -H \"X-auth-access-token: $TOKEN\"",
            ]
            if body is not None:
                rendered = json.dumps(body, indent=2)
                command[-1] += " \\"
                command.append(f"  -d '{rendered}'")

            calls.append(
                {
                    "method": method,
                    "path": url,
                    "name": entry["name"],
                    "action": entry["action"],
                    "entity": entry.get("entity", ""),
                    "body": body,
                    "cli": "\n".join(command),
                }
            )
        return calls

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
                action = entry["action"]
                is_rule = entry.get("target") == "access_rule"
                try:
                    if action == "create":
                        if is_rule:
                            created = fmc.create_access_rule(entry["policy_id"], entry["payload"])
                            undo = {
                                "target": "access_rule", "action": "delete",
                                "policy_id": entry["policy_id"], "id": created.get("id"),
                            }
                        else:
                            created = fmc.create_object(entry["kind"], entry["payload"])
                            undo = {
                                "target": "object", "action": "delete",
                                "kind": entry["kind"], "id": created.get("id"),
                            }
                        details.append({**entry, "status": "created", "id": created.get("id"), "undo": undo})

                    elif action == "update":
                        if is_rule:
                            fmc.update_access_rule(entry["policy_id"], entry["id"], entry["payload"])
                            undo = {
                                "target": "access_rule", "action": "update",
                                "policy_id": entry["policy_id"], "id": entry["id"],
                                "payload": entry.get("before"),
                            }
                        else:
                            fmc.update_object(entry["kind"], entry["id"], entry["payload"])
                            undo = {
                                "target": "object", "action": "update",
                                "kind": entry["kind"], "id": entry["id"],
                                "payload": entry.get("before"),
                            }
                        details.append({**entry, "status": "updated", "undo": undo})

                    else:
                        if is_rule:
                            fmc.delete_access_rule(entry["policy_id"], entry["id"])
                            undo = {
                                "target": "access_rule", "action": "create",
                                "policy_id": entry["policy_id"], "payload": entry.get("before"),
                            }
                        else:
                            fmc.delete_object(entry["kind"], entry["id"])
                            undo = {
                                "target": "object", "action": "create",
                                "kind": entry["kind"], "payload": entry.get("before"),
                            }
                        details.append({**entry, "status": "deleted", "undo": undo})

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
                is_rule = undo.get("target") == "access_rule"
                try:
                    if undo["action"] == "delete":
                        if is_rule:
                            fmc.delete_access_rule(undo["policy_id"], undo["id"])
                        else:
                            fmc.delete_object(undo["kind"], undo["id"])
                    elif undo["action"] == "update":
                        if is_rule:
                            fmc.update_access_rule(undo["policy_id"], undo["id"], undo["payload"])
                        else:
                            fmc.update_object(undo["kind"], undo["id"], undo["payload"])
                    else:
                        payload = {k: v for k, v in (undo.get("payload") or {}).items() if k != "id"}
                        if is_rule:
                            fmc.create_access_rule(undo["policy_id"], payload)
                        else:
                            fmc.create_object(undo["kind"], payload)
                    applied += 1
                    details.append({"name": entry.get("name"), "status": "reverted"})
                except FmcError as exc:
                    failed += 1
                    details.append({"name": entry.get("name"), "status": "failed", "error": str(exc)})

        return DeploymentResult(ok=failed == 0, applied=applied, failed=failed, details=details)

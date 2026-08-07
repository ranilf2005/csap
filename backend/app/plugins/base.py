"""Plugin contract shared by every Cisco security product supported by CSAP.

Adding a new product (ISE, Umbrella, Duo, XDR, Secure Access, ...) means adding a
package under `app.plugins` that subclasses `SecurityPlugin`. The core platform
(auth, jobs, snapshots, reporting, audit) never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProgressCallback(Protocol):
    def __call__(self, percent: int, message: str) -> None: ...


@dataclass(frozen=True)
class PluginManifest:
    key: str
    display_name: str
    vendor: str = "Cisco"
    description: str = ""
    default_port: int = 443
    # Which delivery engines this plugin can execute changes through.
    engines: tuple[str, ...] = ("rest",)
    # Entity types this plugin can discover; drives the dynamic Excel workbook tabs.
    entity_types: tuple[str, ...] = ()
    min_product_version: str | None = None


@dataclass
class ConnectionContext:
    """Everything a plugin needs to talk to one managed system."""

    host: str
    port: int
    username: str
    password: str
    verify_tls: bool = True

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"


@dataclass
class ConnectionResult:
    ok: bool
    product_version: str | None = None
    detail: str = ""


@dataclass
class DiscoveryResult:
    product_version: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


@dataclass
class ValidationIssue:
    severity: str  # error | warning | info
    sheet: str
    row: int | None
    field: str | None
    message: str
    remediation: str = ""  # what the user should actually do about it


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


@dataclass
class ChangePlan:
    """Ordered, engine-agnostic set of intended changes. Rendered by REST/Ansible/Terraform."""

    creates: list[dict[str, Any]] = field(default_factory=list)
    updates: list[dict[str, Any]] = field(default_factory=list)
    deletes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.creates) + len(self.updates) + len(self.deletes)


@dataclass
class DeploymentResult:
    ok: bool
    applied: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


class SecurityPlugin(ABC):
    """Uniform lifecycle every Cisco security product plugin implements."""

    manifest: PluginManifest

    #: Template sheets shown for reference but not yet deployable.
    reference_sheets: frozenset[str] = frozenset()

    @abstractmethod
    def test_connection(self, ctx: ConnectionContext) -> ConnectionResult:
        """Authenticate and return the detected product version."""

    @abstractmethod
    def discover(self, ctx: ConnectionContext, progress: ProgressCallback | None = None) -> DiscoveryResult:
        """Read the current configuration from the managed system."""

    @abstractmethod
    def template_spec(self, discovery: DiscoveryResult | None = None) -> dict[str, list[str]]:
        """Sheet name -> column headers, used to build the dynamic Excel workbook."""

    def existing_rows(self, discovery: DiscoveryResult) -> dict[str, list[dict[str, Any]]]:
        """Current configuration as workbook rows, so users can see and edit what already exists.

        Rows are written with a blank `action`, which the validator ignores.
        """
        return {}

    def field_guide(self) -> dict[str, dict[str, tuple[str, str, str]]]:
        """sheet -> column -> (requirement, description, example), for in-workbook guidance."""
        return {}

    @abstractmethod
    def validate(self, rows: dict[str, list[dict[str, Any]]], discovery: DiscoveryResult) -> ValidationResult:
        """Check an uploaded workbook against schema rules and live inventory."""

    @abstractmethod
    def plan(self, rows: dict[str, list[dict[str, Any]]], discovery: DiscoveryResult) -> ChangePlan:
        """Diff the desired state against discovered state."""

    def preview(self, plan: ChangePlan, host: str | None = None) -> list[dict[str, Any]]:
        """The exact calls a real deployment would make, for the operator to review first."""
        return []

    @abstractmethod
    def deploy(
        self,
        ctx: ConnectionContext,
        plan: ChangePlan,
        engine: str = "rest",
        dry_run: bool = True,
        progress: ProgressCallback | None = None,
    ) -> DeploymentResult:
        """Apply the change plan through the selected delivery engine."""

    def rollback(self, ctx: ConnectionContext, result: DeploymentResult) -> DeploymentResult:
        raise NotImplementedError(f"{self.manifest.key} does not support rollback yet")

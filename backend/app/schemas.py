from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -- auth -------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 scheme name, not a secret
    expires_in: int
    must_change_password: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=72)


class UserOut(ORMModel):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    must_change_password: bool


# -- plugins ----------------------------------------------------------------
class PluginOut(BaseModel):
    key: str
    display_name: str
    vendor: str
    description: str
    default_port: int
    engines: list[str]
    entity_types: list[str]


# -- connections ------------------------------------------------------------
class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    product: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    verify_tls: bool = True


class ConnectionUpdate(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    verify_tls: bool | None = None
    is_active: bool | None = None


class ConnectionOut(ORMModel):
    id: str
    name: str
    product: str
    host: str
    port: int
    username: str
    verify_tls: bool
    is_active: bool
    last_status: str
    last_error: str | None
    detected_version: str | None
    created_at: datetime


class ConnectionTestResult(BaseModel):
    ok: bool
    product_version: str | None = None
    detail: str = ""


# -- jobs / discovery -------------------------------------------------------
class JobOut(ORMModel):
    id: str
    connection_id: str | None
    job_type: str
    status: Literal["pending", "running", "succeeded", "failed"]
    progress: int
    message: str | None
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SnapshotOut(ORMModel):
    id: str
    connection_id: str
    label: str
    product: str
    product_version: str | None
    object_count: int
    summary: dict[str, Any] | None
    created_at: datetime


class InventoryItemOut(ORMModel):
    id: str
    item_type: str
    external_id: str | None
    name: str | None
    payload: dict[str, Any]


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class InventoryPage(BaseModel):
    meta: PageMeta
    items: list[InventoryItemOut]


# -- changes ----------------------------------------------------------------
class ValidationIssueOut(BaseModel):
    severity: Literal["error", "warning", "info"]
    sheet: str
    row: int | None = None
    field: str | None = None
    message: str


class ChangeRequestOut(ORMModel):
    id: str
    connection_id: str
    snapshot_id: str | None
    filename: str
    status: str
    error_count: int
    warning_count: int
    change_count: int
    validation: dict[str, Any] | None
    plan: dict[str, Any] | None
    deployment: dict[str, Any] | None
    created_at: datetime


class ChangeRequestSummary(ORMModel):
    id: str
    connection_id: str
    filename: str
    status: str
    error_count: int
    warning_count: int
    change_count: int
    created_at: datetime


class DeployRequest(BaseModel):
    dry_run: bool = True
    engine: str = "rest"
    confirm: bool = False


# -- reports ----------------------------------------------------------------
class ReportOut(ORMModel):
    id: str
    kind: str
    title: str
    connection_id: str | None
    subject_id: str | None
    summary: dict[str, Any] | None
    created_at: datetime


# -- drift ------------------------------------------------------------------
class DriftRequest(BaseModel):
    baseline_snapshot_id: str
    current_snapshot_id: str


class DriftOut(BaseModel):
    report_id: str
    added: int
    removed: int
    modified: int
    has_drift: bool


# -- audit ------------------------------------------------------------------
class AuditLogOut(ORMModel):
    id: str
    actor: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    source_ip: str | None
    created_at: datetime

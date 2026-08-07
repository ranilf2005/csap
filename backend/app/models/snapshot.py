from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class Snapshot(Base, TimestampMixin):
    """Point-in-time capture of a system's configuration, used for drift detection."""

    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    product: Mapped[str] = mapped_column(String(64), nullable=False)
    product_version: Mapped[str | None] = mapped_column(String(64))
    object_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    artifact_path: Mapped[str | None] = mapped_column(Text)


class InventoryItem(Base, TimestampMixin):
    """A single discovered entity (network object, ACP rule, NAT rule, endpoint, ...)."""

    __tablename__ = "inventory_items"
    __table_args__ = (Index("ix_inventory_snapshot_type", "snapshot_id", "item_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str | None] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

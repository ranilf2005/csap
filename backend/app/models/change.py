from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid

# uploaded -> validated | invalid -> planned -> deploying -> deployed | failed
CHANGE_STATUSES = (
    "uploaded",
    "validated",
    "invalid",
    "planned",
    "deploying",
    "deployed",
    "failed",
    "rolled_back",
)


class ChangeRequest(Base, TimestampMixin):
    """An uploaded workbook and everything derived from it: rows, issues, plan, outcome."""

    __tablename__ = "change_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("snapshots.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="SET NULL"))

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True, nullable=False)

    rows: Mapped[dict | None] = mapped_column(JSONB)
    validation: Mapped[dict | None] = mapped_column(JSONB)
    plan: Mapped[dict | None] = mapped_column(JSONB)
    deployment: Mapped[dict | None] = mapped_column(JSONB)

    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    change_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(36))

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class Report(Base, TimestampMixin):
    """A generated HTML artifact stored on disk under DATA_DIR/reports."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[str | None] = mapped_column(String(36))

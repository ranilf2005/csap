from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class Connection(Base, TimestampMixin):
    """A managed Cisco security system. `product` selects which plugin handles it."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    product: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=443, nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    detected_version: Mapped[str | None] = mapped_column(String(64))

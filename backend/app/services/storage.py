"""Filesystem layout for generated artifacts. Nothing large goes into the database."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def data_root() -> Path:
    return Path(settings.data_dir)


def _ensure(sub: str) -> Path:
    path = data_root() / sub
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir() -> Path:
    return _ensure("uploads")


def reports_dir() -> Path:
    return _ensure("reports")


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip any path component and unsafe characters from a client-supplied name."""
    stem = Path(name).name
    cleaned = _SAFE.sub("_", stem).strip("._-")
    return cleaned[:120] or fallback


def resolve_within(base: Path, candidate: str) -> Path:
    """Reject any stored path that escapes its base directory."""
    resolved = Path(candidate).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError("path escapes its storage directory")
    return resolved

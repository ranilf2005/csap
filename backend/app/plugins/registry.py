"""Discovers and caches every SecurityPlugin subclass under `app.plugins`."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from functools import lru_cache

import app.plugins as plugins_pkg
from app.plugins.base import SecurityPlugin

logger = logging.getLogger(__name__)


@lru_cache
def _load() -> dict[str, SecurityPlugin]:
    registry: dict[str, SecurityPlugin] = {}
    for module in pkgutil.iter_modules(plugins_pkg.__path__):
        if not module.ispkg:
            continue
        name = f"{plugins_pkg.__name__}.{module.name}"
        try:
            mod = importlib.import_module(f"{name}.plugin")
        except ModuleNotFoundError:
            logger.warning("plugin package %s has no plugin.py; skipping", name)
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, SecurityPlugin) and obj is not SecurityPlugin and not inspect.isabstract(obj):
                instance = obj()
                registry[instance.manifest.key] = instance
                logger.info("registered plugin: %s", instance.manifest.key)
    return registry


def available() -> list[SecurityPlugin]:
    return list(_load().values())


def get(key: str) -> SecurityPlugin:
    try:
        return _load()[key]
    except KeyError:
        raise KeyError(f"unknown product plugin '{key}'") from None

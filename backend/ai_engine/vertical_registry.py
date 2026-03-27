"""Lazy registry for ai_engine vertical modules.

This module is the single selector layer that maps profile identifiers to
vertical engine packages.  Keeping the mapping here avoids direct import-time
coupling between ``ai_engine`` and any specific vertical implementation.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any


@dataclass(frozen=True)
class VerticalEntry:
    profile_name: str
    vertical_name: str
    module_path: str


_REGISTRY: dict[str, VerticalEntry] = {
    "private_credit": VerticalEntry(
        profile_name="private_credit",
        vertical_name="private_credit",
        module_path="vertical_engines.credit",
    ),
    "liquid_funds": VerticalEntry(
        profile_name="liquid_funds",
        vertical_name="liquid_funds",
        module_path="vertical_engines.wealth",
    ),
}


def get_vertical_entry(profile_name: str) -> VerticalEntry:
    """Return the registered vertical entry for ``profile_name``."""
    try:
        return _REGISTRY[profile_name]
    except KeyError as exc:
        raise ValueError(
            f"No vertical engine registered for profile: {profile_name!r}. "
            f"Available: {sorted(_REGISTRY)}",
        ) from exc


def import_vertical_module(profile_name: str) -> ModuleType:
    """Import the registered vertical module for ``profile_name`` lazily."""
    entry = get_vertical_entry(profile_name)
    return importlib.import_module(entry.module_path)


def resolve_vertical_export(profile_name: str, export_name: str) -> Any:
    """Resolve one export from a registered vertical module lazily."""
    module = import_vertical_module(profile_name)
    try:
        return getattr(module, export_name)
    except AttributeError as exc:
        raise AttributeError(
            f"Vertical module {module.__name__!r} does not export {export_name!r}",
        ) from exc


def available_profiles() -> list[str]:
    """Return the registered profile identifiers in sorted order."""
    return sorted(_REGISTRY)

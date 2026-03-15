"""Macroeconomic data time-series — backward-compatible re-export.

Canonical location: app.shared.models.MacroData
This re-export will be removed after migration is verified.
"""

# Re-export from canonical location
from app.shared.models import MacroData  # noqa: F401

__all__ = ["MacroData"]

"""Base critic interface for vertical engines.

Critics perform adversarial review of analysis output — surfacing
fatal flaws, material gaps, and optimism bias that the primary
analysis may have missed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCritic(ABC):
    """Abstract interface for vertical-specific adversarial critique."""

    vertical: str

    @abstractmethod
    def critique(
        self,
        *,
        analysis: dict[str, Any],
        context: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform adversarial critique of an analysis result.

        Parameters
        ----------
        analysis : dict
            The primary analysis output to critique.
        context : dict | None
            Additional context (deal data, macro snapshot, etc.).
        config : dict | None
            Resolved configuration from ConfigService.

        Returns
        -------
        dict
            Critique result with fatal_flaws, material_gaps, etc.
        """

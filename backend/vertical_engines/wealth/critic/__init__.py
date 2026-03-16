"""Critic Engine — adversarial review for wealth DD reports.

Mirrors credit's critic/ package. Sibling to dd_report/ to enable
reuse by content production without circular imports.

Public API:
    critique_dd_report  — never-raises entry point
    CriticVerdict       — frozen result dataclass
"""

from vertical_engines.wealth.critic.models import CriticVerdict
from vertical_engines.wealth.critic.service import critique_dd_report

__all__ = ["CriticVerdict", "critique_dd_report"]

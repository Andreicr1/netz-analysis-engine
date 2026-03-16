"""Asset Universe — fund approval workflow with governance controls.

Provides UniverseService for managing the approved fund universe:
  - Fund approval flow: DD Report → pending → approved/rejected
  - Self-approval prevention (decided_by != created_by)
  - Deactivation with rebalance evaluation trigger
"""

from vertical_engines.wealth.asset_universe.universe_service import UniverseService

__all__ = ["UniverseService"]

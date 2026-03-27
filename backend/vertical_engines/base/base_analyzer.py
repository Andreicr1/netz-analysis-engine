"""Base analyzer interface for vertical engines.

Every vertical engine must provide an analyzer that can run deal-level
and portfolio-level analysis.  The concrete implementation lives in
``vertical_engines/{vertical}/`` and is resolved by :class:`ProfileLoader`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class BaseAnalyzer(ABC):
    """Abstract interface for vertical-specific deal analysis.

    Note: Methods accept sync ``Session`` (not ``AsyncSession``) because
    vertical engine business logic is CPU-bound and runs in sync context.
    Callers in async route handlers must dispatch via ``asyncio.to_thread()``
    or use a sync session obtained outside the async context.
    """

    vertical: str  # e.g. "private_credit", "liquid_funds"

    @abstractmethod
    def run_deal_analysis(
        self,
        db: Session,
        *,
        fund_id: str,
        deal_id: str,
        actor_id: str,
        force: bool = False,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run full deal analysis (IC memo, pipeline intelligence, etc.).

        Parameters
        ----------
        db : Session
            Caller-provided database session (session injection pattern).
        fund_id : str
            Fund identifier (tenant-scoped).
        deal_id : str
            Deal or investment identifier.
        actor_id : str
            User performing the action.
        force : bool
            Re-run even if a recent analysis exists.
        config : dict | None
            Resolved configuration from ConfigService.  If None, the
            implementation should fetch its own defaults.

        Returns
        -------
        dict
            Analysis result (structure is vertical-specific).

        """

    @abstractmethod
    def run_portfolio_analysis(
        self,
        db: Session,
        *,
        fund_id: str,
        actor_id: str,
        as_of: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run portfolio-level analysis (periodic reviews, drift, etc.).

        Parameters
        ----------
        db : Session
            Caller-provided database session.
        fund_id : str
            Fund identifier.
        actor_id : str
            User performing the action.
        as_of : str | None
            Point-in-time date (ISO format).  Defaults to today.
        config : dict | None
            Resolved configuration from ConfigService.

        Returns
        -------
        dict
            Portfolio analysis result.

        """

    def run_pipeline_analysis(
        self,
        db: Session,
        *,
        fund_id: str,
        actor_id: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run pipeline-level analysis (discovery, aggregation, ingest).

        Default implementation returns not-applicable. Verticals that have
        a pipeline concept (e.g. private credit) should override this.

        Parameters
        ----------
        db : Session
            Caller-provided database session.
        fund_id : str
            Fund identifier.
        actor_id : str
            User performing the action.
        config : dict | None
            Resolved configuration from ConfigService.

        Returns
        -------
        dict
            Pipeline analysis result.

        """
        return {"status": "not_applicable", "vertical": self.vertical}

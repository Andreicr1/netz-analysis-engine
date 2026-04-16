"""Worker registry — maps worker names to async entry points.

Used by the Railway Cron CLI (app.workers.cli), the internal dispatch
endpoint, and admin tooling.

Each entry maps a string key to a tuple of:
    (coroutine_function, scope_type, timeout_seconds)

scope_type is either "global" or "org" — org-scoped workers are
dispatched once per active organization.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Timeout tiers (match existing workers.py constants)
_HEAVY = 600   # 10 min
_LIGHT = 300   # 5 min
_BULK = 7200   # 2 hours — for large batch downloads (e.g. brochure PDFs)


def _build_registry() -> dict[str, tuple[Callable[..., Awaitable[Any]], str, int]]:
    """Lazily build the registry to avoid import-time side effects.

    Returns dict of name → (async_fn, scope_type, timeout_seconds).
    """
    from app.domains.wealth.workers.benchmark_ingest import run_benchmark_ingest
    from app.domains.wealth.workers.bis_ingestion import run_bis_ingestion
    from app.domains.wealth.workers.brochure_ingestion import (
        run_brochure_download,
        run_brochure_extract,
    )
    from app.domains.wealth.workers.drift_check import run_drift_check
    from app.domains.wealth.workers.esma_ingestion import run_esma_ingestion
    from app.domains.wealth.workers.fast_track_eviction import run_fast_track_eviction
    from app.domains.wealth.workers.imf_ingestion import run_imf_ingestion
    from app.domains.wealth.workers.instrument_ingestion import run_instrument_ingestion
    from app.domains.wealth.workers.macro_ingestion import run_macro_ingestion
    from app.domains.wealth.workers.nport_fund_discovery import run_nport_fund_discovery
    from app.domains.wealth.workers.nport_ingestion import run_nport_ingestion
    from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion
    from app.domains.wealth.workers.portfolio_eval import run_portfolio_eval
    from app.domains.wealth.workers.portfolio_nav_synthesizer import run_portfolio_nav_synthesizer
    from app.domains.wealth.workers.regime_fit import run_regime_fit
    from app.domains.wealth.workers.risk_calc import run_risk_calc
    from app.domains.wealth.workers.screening_batch import run_screening_batch
    from app.domains.wealth.workers.sec_13f_ingestion import run_sec_13f_ingestion
    from app.domains.wealth.workers.sec_adv_ingestion import run_sec_adv_ingestion
    from app.domains.wealth.workers.sec_refresh import run_sec_refresh
    from app.domains.wealth.workers.tiingo_enrichment import run_tiingo_enrichment
    from app.domains.wealth.workers.treasury_ingestion import run_treasury_ingestion
    from app.domains.wealth.workers.universe_auto_import import (
        run_universe_auto_import,
    )
    from app.domains.wealth.workers.universe_sync import run_universe_sync
    from app.domains.wealth.workers.watchlist_batch import run_watchlist_check
    from app.domains.wealth.workers.wealth_embedding_worker import run_wealth_embedding

    return {
        # ── Global workers (no org_id) ────────────────────────
        "universe_sync": (run_universe_sync, "global", _HEAVY),
        "universe_auto_import": (run_universe_auto_import, "global", _HEAVY),
        "tiingo_enrichment": (run_tiingo_enrichment, "global", _HEAVY),
        "macro_ingestion": (run_macro_ingestion, "global", _HEAVY),
        "benchmark_ingest": (run_benchmark_ingest, "global", _HEAVY),
        "treasury_ingestion": (run_treasury_ingestion, "global", _HEAVY),
        "ofr_ingestion": (run_ofr_ingestion, "global", _HEAVY),
        "bis_ingestion": (run_bis_ingestion, "global", _HEAVY),
        "imf_ingestion": (run_imf_ingestion, "global", _HEAVY),
        "nport_ingestion": (run_nport_ingestion, "global", _HEAVY),
        "nport_fund_discovery": (run_nport_fund_discovery, "global", _HEAVY),

        "esma_ingestion": (run_esma_ingestion, "global", _HEAVY),
        "sec_refresh": (run_sec_refresh, "global", _HEAVY),
        "sec_13f_ingestion": (run_sec_13f_ingestion, "global", _HEAVY),
        "sec_adv_ingestion": (run_sec_adv_ingestion, "global", _HEAVY),
        "brochure_download": (run_brochure_download, "global", _BULK),
        "brochure_extract": (run_brochure_extract, "global", _BULK),
        "wealth_embedding": (run_wealth_embedding, "global", _BULK),
        "drift_check": (run_drift_check, "global", _LIGHT),
        "regime_fit": (run_regime_fit, "global", _LIGHT),
        "fast_track_eviction": (run_fast_track_eviction, "global", _LIGHT),
        # ── Org-scoped workers (dispatched per active org) ────
        "instrument_ingestion": (run_instrument_ingestion, "global", _HEAVY),
        "risk_calc": (run_risk_calc, "org", _HEAVY),
        "portfolio_eval": (run_portfolio_eval, "org", _LIGHT),
        "portfolio_nav_synthesizer": (run_portfolio_nav_synthesizer, "org", _LIGHT),
        "screening_batch": (run_screening_batch, "org", _LIGHT),
        "watchlist_batch": (run_watchlist_check, "org", _LIGHT),
    }


_registry: dict[str, tuple[Callable[..., Awaitable[Any]], str, int]] | None = None


def get_worker_registry() -> dict[str, tuple[Callable[..., Awaitable[Any]], str, int]]:
    """Return the singleton worker registry (lazy init)."""
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry

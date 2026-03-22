"""Worker registry — maps worker names to async entry points.

Used by the internal dispatch endpoint (Cloudflare Cron Workers)
and can be imported by other admin tooling.

Each entry maps a string key to a tuple of:
    (coroutine_function, scope_type, timeout_seconds)

scope_type is either "global" or "org" — org-scoped workers are
dispatched once per active organization by the dispatch endpoint.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Timeout tiers (match existing workers.py constants)
_HEAVY = 600  # 10 min
_LIGHT = 300  # 5 min


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
    from app.domains.wealth.workers.imf_ingestion import run_imf_ingestion
    from app.domains.wealth.workers.ingestion import run_ingestion
    from app.domains.wealth.workers.instrument_ingestion import run_instrument_ingestion
    from app.domains.wealth.workers.macro_ingestion import run_macro_ingestion
    from app.domains.wealth.workers.nport_ingestion import run_nport_ingestion
    from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion
    from app.domains.wealth.workers.portfolio_eval import run_portfolio_eval
    from app.domains.wealth.workers.regime_fit import run_regime_fit
    from app.domains.wealth.workers.risk_calc import run_risk_calc
    from app.domains.wealth.workers.screening_batch import run_screening_batch
    from app.domains.wealth.workers.sec_refresh import run_sec_refresh
    from app.domains.wealth.workers.treasury_ingestion import run_treasury_ingestion
    from app.domains.wealth.workers.watchlist_batch import run_watchlist_check

    return {
        # ── Global workers (no org_id) ────────────────────────
        "macro_ingestion": (run_macro_ingestion, "global", _HEAVY),
        "benchmark_ingest": (run_benchmark_ingest, "global", _HEAVY),
        "treasury_ingestion": (run_treasury_ingestion, "global", _HEAVY),
        "ofr_ingestion": (run_ofr_ingestion, "global", _HEAVY),
        "bis_ingestion": (run_bis_ingestion, "global", _HEAVY),
        "imf_ingestion": (run_imf_ingestion, "global", _HEAVY),
        "nport_ingestion": (run_nport_ingestion, "global", _HEAVY),
        "sec_refresh": (run_sec_refresh, "global", _HEAVY),
        "brochure_download": (run_brochure_download, "global", _HEAVY),
        "brochure_extract": (run_brochure_extract, "global", _HEAVY),
        "drift_check": (run_drift_check, "global", _LIGHT),
        "regime_fit": (run_regime_fit, "global", _LIGHT),
        # ── Org-scoped workers (dispatched per active org) ────
        "ingestion": (run_ingestion, "org", _HEAVY),
        "instrument_ingestion": (run_instrument_ingestion, "org", _HEAVY),
        "risk_calc": (run_risk_calc, "org", _HEAVY),
        "portfolio_eval": (run_portfolio_eval, "org", _LIGHT),
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

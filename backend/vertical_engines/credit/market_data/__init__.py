"""Market Data Engine v2 — deterministic FRED macro overlay for Deep Review v4.

Public API:
    get_macro_snapshot()              — daily-cached macro snapshot (orchestrator)
    compute_macro_stress_severity()   — graded stress assessment
    compute_macro_stress_flag()       — legacy bool stress flag
    resolve_metro_key()               — geography → Case-Shiller metro key
    fetch_regional_case_shiller()     — regional HPI fetch

Error contract: never-raises (orchestration engine called during deep review).
Returns snapshot with stress severity embedded.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vertical_engines.credit.market_data.models import (
        FRED_SERIES_REGISTRY as FRED_SERIES_REGISTRY,
    )
    from vertical_engines.credit.market_data.regional import (
        fetch_regional_case_shiller as fetch_regional_case_shiller,
    )
    from vertical_engines.credit.market_data.regional import (
        resolve_metro_key as resolve_metro_key,
    )
    from vertical_engines.credit.market_data.service import (
        get_macro_snapshot as get_macro_snapshot,
    )
    from vertical_engines.credit.market_data.stress import (
        compute_macro_stress_flag as compute_macro_stress_flag,
    )
    from vertical_engines.credit.market_data.stress import (
        compute_macro_stress_severity as compute_macro_stress_severity,
    )


def __getattr__(name: str) -> Any:
    if name == "get_macro_snapshot":
        from vertical_engines.credit.market_data.service import get_macro_snapshot

        return get_macro_snapshot
    if name == "compute_macro_stress_severity":
        from vertical_engines.credit.market_data.stress import compute_macro_stress_severity

        return compute_macro_stress_severity
    if name == "compute_macro_stress_flag":
        from vertical_engines.credit.market_data.stress import compute_macro_stress_flag

        return compute_macro_stress_flag
    if name == "resolve_metro_key":
        from vertical_engines.credit.market_data.regional import resolve_metro_key

        return resolve_metro_key
    if name == "fetch_regional_case_shiller":
        from vertical_engines.credit.market_data.regional import fetch_regional_case_shiller

        return fetch_regional_case_shiller
    if name == "FRED_SERIES_REGISTRY":
        from vertical_engines.credit.market_data.models import FRED_SERIES_REGISTRY

        return FRED_SERIES_REGISTRY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FRED_SERIES_REGISTRY",
    "compute_macro_stress_flag",
    "compute_macro_stress_severity",
    "fetch_regional_case_shiller",
    "get_macro_snapshot",
    "resolve_metro_key",
]

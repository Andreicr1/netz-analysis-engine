"""ELITE ranking — global top-300 fund selection proportional to
the default strategic allocation. Used by the ``risk_calc`` global
worker (lock 900_071) to populate ``fund_risk_metrics.elite_flag``
and its companion columns.

See ``allocation_source`` for the authoritative strategic weights
source resolution (Phase 2 Session B commit 6) and the README-style
docstring on ``get_global_default_strategy_weights``.
"""

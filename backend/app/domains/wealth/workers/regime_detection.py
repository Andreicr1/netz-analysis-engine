"""Global regime detection worker — computes macro_regime_snapshot.

Usage:
    python -m app.domains.wealth.workers.regime_detection

Must run AFTER macro_ingestion (lock 43) and BEFORE risk_calc (lock 900_007).
Schedule at 02:30 UTC (macro_ingestion ~02:00, risk_calc ~03:00).

Advisory lock ID = 900_130.
"""
from __future__ import annotations

import asyncio

from app.domains.wealth.workers.risk_calc import run_global_regime_detection

if __name__ == "__main__":
    asyncio.run(run_global_regime_detection())

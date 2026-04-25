"""IPCA preprocessing helpers (KP-S 2019 conventions)."""
from __future__ import annotations

import pandas as pd


def rank_transform(chars: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional rank -> [-0.5, +0.5] per period.

    Ranks each characteristic within each cross-section (per time period
    in the MultiIndex level=1) and rescales to [-0.5, +0.5]. Robust to
    outliers in heavy-tailed inputs like book_to_market and
    investment_growth. Per-period ranking is leakage-free: train and
    test cross-sections are entirely disjoint by date.

    Input:  DataFrame with MultiIndex (instrument_id, as_of), one column
            per characteristic. NaNs allowed (skipped by ``rank``).
    Output: same shape, values in [-0.5, +0.5].
    """
    return chars.groupby(level=1).transform(lambda g: g.rank(pct=True) - 0.5)

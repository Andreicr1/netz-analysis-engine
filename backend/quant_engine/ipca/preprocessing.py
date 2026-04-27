"""IPCA preprocessing helpers (KP-S 2019 conventions)."""
from __future__ import annotations

import pandas as pd


def rank_transform(chars: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional rank -> [-0.5, +0.5] per period.

    Ranks each characteristic within each cross-section (per time period
    in the MultiIndex) and rescales to [-0.5, +0.5]. Robust to outliers
    in heavy-tailed inputs like book_to_market and investment_growth.
    Per-period ranking is leakage-free: train and test cross-sections
    are entirely disjoint by date.

    PR-Q36 F05: time level extracted dynamically by name ("date", "month",
    "as_of") with positional fallback to level=1. Defense-in-depth against
    future callers passing a MultiIndex with date at level=0.

    Input:  DataFrame with MultiIndex (instrument_id, as_of), one column
            per characteristic. NaNs allowed (skipped by ``rank``).
    Output: same shape, values in [-0.5, +0.5].
    """
    if not isinstance(chars.index, pd.MultiIndex):
        return chars.transform(lambda g: g.rank(pct=True) - 0.5)

    if "date" in chars.index.names:
        time_level = "date"
    elif "month" in chars.index.names:
        time_level = "month"
    elif "as_of" in chars.index.names:
        time_level = "as_of"
    else:
        time_level = 1

    return chars.groupby(level=time_level).transform(lambda g: g.rank(pct=True) - 0.5)

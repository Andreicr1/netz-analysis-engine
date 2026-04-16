"""Layer 3 of the universe pre-filter cascade — correlation dedup.

Collapses highly-correlated peer funds (|ρ| > threshold over 1Y daily
returns) into single representatives via union-find clustering. The
representative per cluster is the fund with the highest manager_score,
tiebreak on instrument_id ASC for determinism.

Why this exists
---------------
Post PR-A7 the cascade hands the fund-level optimizer 269-319 candidates
that share substantial common variance (50 S&P 500 trackers, 50 AGG-like
bond funds, etc.). The resulting covariance matrix is rank-deficient with
κ(Σ) ≈ 5e5-7e5 — orders of magnitude above the PR-A1 error threshold
(1e4) — so ``compute_fund_level_inputs`` raises
``IllConditionedCovarianceError`` and every build fails. Layer 3 trims the
duplicates so CLARABEL receives a tractable 80-150 fund universe whose
Σ is conditionable after Ledoit-Wolf shrinkage.

Honest tradeoff
---------------
The default threshold ``0.95`` is the quant-architect's recommendation. It
may be too permissive in stress regimes where everything correlates, or
too strict on diversified universes. The service emits the observed p50
and p95 of the absolute pairwise correlation distribution so the operator
can calibrate empirically after 2-3 real runs (see
``feedback_retrieval_thresholds.md`` — never trust an absolute threshold
without measuring it on real data).
"""
from __future__ import annotations

import time
import typing
import uuid
from datetime import date, timedelta
from typing import Any

import numpy as np
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.services.quant_queries import (
    _align_returns_with_ffill,
    _fetch_returns_by_type,
)

logger: Any = structlog.get_logger()


# ── Defaults ───────────────────────────────────────────────────────────

#: Quant-architect recommendation; tune via telemetry (see module docstring).
DEFAULT_CORR_THRESHOLD: float = 0.95

#: 1Y daily window — dedup is about *current* peer structure, not 5Y blend.
DEFAULT_WINDOW_DAYS: int = 252

#: 3M minimum per fund. Below this, skip clustering and keep as singleton
#: (conservative — err toward keeping rather than collapsing on thin data).
MIN_OBSERVATIONS_FOR_DEDUP: int = 63


class DedupResult(typing.NamedTuple):
    """Return shape for :func:`dedup_correlated_funds`.

    Fields
    ------
    kept_ids
        UUIDs surviving the dedup — one representative per cluster, plus
        every singleton (skipped funds and zero-variance funds).
    cluster_map
        ``instrument_id → cluster_id``. ``cluster_id`` is the representative
        UUID of the cluster, so members and rep share the same value.
    n_clusters
        Number of distinct clusters formed (== ``len(kept_ids)`` when no
        singletons were produced; ≤ when singletons exist).
    n_input
        Number of UUIDs the caller passed in.
    threshold_used
        ``|ρ|`` cutoff actually applied (echo of the parameter).
    pair_corr_p50
        Observed median of all upper-triangle absolute pairwise
        correlations across funds with sufficient data. Telemetry only.
    pair_corr_p95
        Observed 95th percentile. Telemetry only.
    skipped_no_data
        UUIDs that were excluded from the correlation computation because
        they had < ``MIN_OBSERVATIONS_FOR_DEDUP`` valid returns. They are
        still present in ``kept_ids`` (returned as singletons).
    duration_ms
        Total wall time in milliseconds.
    """

    kept_ids: list[uuid.UUID]
    cluster_map: dict[uuid.UUID, uuid.UUID]
    n_clusters: int
    n_input: int
    threshold_used: float
    pair_corr_p50: float
    pair_corr_p95: float
    skipped_no_data: list[uuid.UUID]
    duration_ms: int


# ── Union-find ─────────────────────────────────────────────────────────


class _UnionFind:
    """Classic disjoint-set with path compression and union-by-rank.

    Keys are arbitrary hashable values (we use ``int`` indices). Internal
    use only — not exposed.
    """

    def __init__(self, items: typing.Iterable[int]) -> None:
        self._parent: dict[int, int] = {i: i for i in items}
        self._rank: dict[int, int] = {i: 0 for i in self._parent}

    def find(self, x: int) -> int:
        # Iterative path compression to avoid recursion depth on large N.
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        node = x
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            self._parent[ra] = rb
        elif self._rank[ra] > self._rank[rb]:
            self._parent[rb] = ra
        else:
            self._parent[rb] = ra
            self._rank[ra] += 1

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for node in self._parent:
            root = self.find(node)
            out.setdefault(root, []).append(node)
        return out


# ── Main entry ─────────────────────────────────────────────────────────


async def dedup_correlated_funds(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    manager_scores: dict[uuid.UUID, float | None],
    *,
    threshold: float = DEFAULT_CORR_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    as_of_date: date | None = None,
) -> DedupResult:
    """Collapse highly-correlated peer funds via union-find clustering.

    Algorithm
    ---------
    1. Fetch 1Y daily returns from ``nav_timeseries`` via
       :func:`_fetch_returns_by_type` (log preferred, arithmetic fallback).
    2. Per-fund obs count: if a fund has fewer than
       ``MIN_OBSERVATIONS_FOR_DEDUP`` valid points, mark it as a singleton
       (kept verbatim, never clustered).
    3. Align the remaining funds via :func:`_align_returns_with_ffill`
       (forward-fill ≤ 2 days, then strict inner-join on dates). If the
       resulting common matrix has < ``MIN_OBSERVATIONS_FOR_DEDUP`` rows,
       skip clustering entirely and return everything as singletons.
    4. Identify zero-variance columns (constant returns produce undefined
       correlation) — treat as singletons too.
    5. Compute the N×N Pearson correlation matrix on the active subset.
    6. Union-find: for every upper-triangle pair (i, j) with
       ``|ρ| > threshold``, union i and j. ``abs()`` is intentional —
       a pair correlated at -0.99 is as colinear as +0.99 for Σ
       conditioning, so they belong in the same cluster.
    7. Per cluster, elect representative: highest ``manager_score``
       (None scores rank last), tiebreak ``instrument_id ASC`` so
       output is reproducible across query planner choices.
    8. Compute observed p50 and p95 of the absolute upper-triangle
       correlations *before* clustering — telemetry for threshold
       calibration.

    Performance budget
    ------------------
    N=320: corrcoef ~50ms, union-find pair scan O(N²) ~50ms, DB fetch
    1-2s. Total wall ~1-3s, well inside the 120s construction budget.

    Conservative posture
    --------------------
    Funds skipped at steps 2 and 4 are *kept* in the output as singletons
    — we err toward retaining a fund the optimizer might prune, rather
    than dropping a fund the operator approved.

    Caller responsibility
    ---------------------
    If ``len(kept_ids) < 2`` after dedup, the caller MUST surface a
    ``failure_reason='dedup_collapsed_too_far'`` instead of feeding a
    one-fund universe to the optimizer (spec §F bullet 10). The service
    itself does not raise on this — it would prevent isolated unit tests
    of legitimate "5 perfect duplicates → 1 representative" behaviour.
    """
    started = time.perf_counter()

    if as_of_date is None:
        as_of_date = date.today()
    lookback_start = as_of_date - timedelta(days=int(window_days * 1.5))

    n_input = len(fund_ids)
    cluster_map: dict[uuid.UUID, uuid.UUID]
    if n_input == 0:
        return DedupResult(
            kept_ids=[],
            cluster_map={},
            n_clusters=0,
            n_input=0,
            threshold_used=float(threshold),
            pair_corr_p50=0.0,
            pair_corr_p95=0.0,
            skipped_no_data=[],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # ── 1. Fetch returns ──────────────────────────────────────────────
    fund_returns_str_keyed, used_return_type = await _fetch_returns_by_type(
        db, fund_ids, lookback_start, as_of_date,
    )

    # ── 2. Identify funds with insufficient observations ──────────────
    skipped_no_data: list[uuid.UUID] = []
    candidate_ids: list[uuid.UUID] = []
    for uid in fund_ids:
        n_obs = len(fund_returns_str_keyed.get(str(uid), {}))
        if n_obs < MIN_OBSERVATIONS_FOR_DEDUP:
            skipped_no_data.append(uid)
        else:
            candidate_ids.append(uid)

    # If we have fewer than 2 candidates with usable data, no clustering
    # is possible — return everything (skipped + candidates) as singletons.
    if len(candidate_ids) < 2:
        kept = list(fund_ids)
        cluster_map = {uid: uid for uid in kept}
        result = DedupResult(
            kept_ids=kept,
            cluster_map=cluster_map,
            n_clusters=len(kept),
            n_input=n_input,
            threshold_used=float(threshold),
            pair_corr_p50=0.0,
            pair_corr_p95=0.0,
            skipped_no_data=skipped_no_data,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        _emit_log(result, used_return_type=used_return_type)
        return result

    # ── 3. Align candidate returns ────────────────────────────────────
    candidate_str_ids = [str(uid) for uid in candidate_ids]
    returns_matrix, common_dates = _align_returns_with_ffill(
        fund_returns_str_keyed, candidate_str_ids,
    )

    if len(common_dates) < MIN_OBSERVATIONS_FOR_DEDUP:
        # Aligned window collapsed below the minimum — universe is too
        # heterogeneous to cluster safely. Conservative: pass everything.
        kept = list(fund_ids)
        cluster_map = {uid: uid for uid in kept}
        logger.warning(
            "correlation_dedup.aligned_window_too_short",
            n_input=n_input,
            common_dates=len(common_dates),
            min_required=MIN_OBSERVATIONS_FOR_DEDUP,
        )
        result = DedupResult(
            kept_ids=kept,
            cluster_map=cluster_map,
            n_clusters=len(kept),
            n_input=n_input,
            threshold_used=float(threshold),
            pair_corr_p50=0.0,
            pair_corr_p95=0.0,
            skipped_no_data=skipped_no_data,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        _emit_log(result, used_return_type=used_return_type)
        return result

    # Truncate to the requested 1Y window (alignment may have pulled more
    # via ffill on long histories — we want the most recent N days).
    if returns_matrix.shape[0] > window_days:
        returns_matrix = returns_matrix[-window_days:]

    # ── 4. Mask zero-variance columns ─────────────────────────────────
    col_std = returns_matrix.std(axis=0, ddof=0)
    active_mask = col_std > 0.0
    active_indices = np.where(active_mask)[0].tolist()
    inactive_indices = np.where(~active_mask)[0].tolist()
    inactive_uuids = [candidate_ids[i] for i in inactive_indices]

    if len(active_indices) < 2:
        # Every candidate had constant returns — no correlation possible.
        kept = list(fund_ids)
        cluster_map = {uid: uid for uid in kept}
        logger.warning(
            "correlation_dedup.no_active_columns",
            n_input=n_input,
            n_zero_variance=len(inactive_indices),
        )
        result = DedupResult(
            kept_ids=kept,
            cluster_map=cluster_map,
            n_clusters=len(kept),
            n_input=n_input,
            threshold_used=float(threshold),
            pair_corr_p50=0.0,
            pair_corr_p95=0.0,
            skipped_no_data=skipped_no_data,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        _emit_log(result, used_return_type=used_return_type)
        return result

    active_uuids = [candidate_ids[i] for i in active_indices]
    active_returns = returns_matrix[:, active_indices]

    # ── 5. Correlation matrix on active subset ────────────────────────
    # Suppress numpy warnings for any residual NaN — defensive only;
    # ddof guard above should have eliminated divide-by-zero.
    with np.errstate(invalid="ignore", divide="ignore"):
        corr_full = np.corrcoef(active_returns, rowvar=False)

    # ``np.corrcoef`` returns a scalar 1.0 for n=1, sanity guard:
    corr_matrix = np.atleast_2d(corr_full)
    abs_corr = np.abs(corr_matrix)
    # Replace any NaN that slipped through (e.g. one side fully constant
    # in a sub-window) with 0 — unrelated, no clustering.
    abs_corr = np.nan_to_num(abs_corr, nan=0.0)

    # Telemetry: percentiles of the upper triangle (k=1 excludes diagonal)
    n = abs_corr.shape[0]
    iu = np.triu_indices(n, k=1)
    upper = abs_corr[iu] if iu[0].size > 0 else np.array([0.0])
    pair_corr_p50 = float(np.percentile(upper, 50))
    pair_corr_p95 = float(np.percentile(upper, 95))

    # ── 6. Union-find clustering ──────────────────────────────────────
    uf = _UnionFind(range(n))
    # Iterate the upper triangle; threshold is on absolute correlation.
    pair_mask = abs_corr > float(threshold)
    rows, cols = np.where(np.triu(pair_mask, k=1))
    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        uf.union(int(i), int(j))

    # ── 7. Elect representatives ──────────────────────────────────────
    cluster_map = {}
    kept_ids: list[uuid.UUID] = []

    for _root, members in uf.groups().items():
        member_uuids = [active_uuids[m] for m in members]
        # Sort by (-score_or_neg_inf, str(uuid)) so highest score wins,
        # tiebreak by UUID ASC. ``None`` scores fall to the bottom.
        rep = sorted(
            member_uuids,
            key=lambda uid: (
                -(manager_scores.get(uid) or float("-inf")),
                str(uid),
            ),
        )[0]
        kept_ids.append(rep)
        for mid in member_uuids:
            cluster_map[mid] = rep

    n_clusters = len(kept_ids)

    # Singletons from skipped (insufficient obs) and zero-variance funds
    # are kept verbatim and never clustered.
    for uid in inactive_uuids:
        cluster_map[uid] = uid
        kept_ids.append(uid)
    for uid in skipped_no_data:
        cluster_map[uid] = uid
        kept_ids.append(uid)

    duration_ms = int((time.perf_counter() - started) * 1000)

    result = DedupResult(
        kept_ids=kept_ids,
        cluster_map=cluster_map,
        n_clusters=n_clusters,
        n_input=n_input,
        threshold_used=float(threshold),
        pair_corr_p50=pair_corr_p50,
        pair_corr_p95=pair_corr_p95,
        skipped_no_data=skipped_no_data,
        duration_ms=duration_ms,
    )
    _emit_log(result, used_return_type=used_return_type)
    return result


# ── Telemetry log ─────────────────────────────────────────────────────


def _emit_log(result: DedupResult, *, used_return_type: str) -> None:
    """One structured log line per invocation — observability for tuning."""
    logger.info(
        "correlation_dedup.completed",
        n_input=result.n_input,
        n_kept=len(result.kept_ids),
        n_clusters=result.n_clusters,
        threshold_used=result.threshold_used,
        pair_corr_p50=round(result.pair_corr_p50, 3),
        pair_corr_p95=round(result.pair_corr_p95, 3),
        duration_ms=result.duration_ms,
        skipped_no_data=len(result.skipped_no_data),
        return_type=used_return_type,
    )

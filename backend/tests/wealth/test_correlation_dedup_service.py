"""Tests for ``correlation_dedup_service`` (PR-A8 — Layer 3 cascade).

Synthetic tests (D.1-D.8) feed pre-built return series via a monkeypatch
on ``_fetch_returns_by_type`` so the suite runs without seeding the live
``nav_timeseries`` hypertable. Integration test (D.9) hits the real
docker-compose DB to confirm the dedup band lands in CLARABEL's feasible
window for the seeded org.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from app.domains.wealth.services import correlation_dedup_service as cds
from app.domains.wealth.services.correlation_dedup_service import (
    DEFAULT_CORR_THRESHOLD,
    DEFAULT_WINDOW_DAYS,
    MIN_OBSERVATIONS_FOR_DEDUP,
    DedupResult,
    dedup_correlated_funds,
)

pytestmark = pytest.mark.asyncio


# ── Synthetic fixtures ───────────────────────────────────────────────


def _trading_dates(n: int, end: date | None = None) -> list[date]:
    """Build a list of ``n`` consecutive business days ending at ``end``.

    Trading-day approximation (Mon-Fri, no holiday calendar) is good
    enough for synthetic correlation tests — the dedup service only
    needs date keys to align matrices.
    """
    end = end or date.today()
    out: list[date] = []
    cur = end
    while len(out) < n:
        if cur.weekday() < 5:  # Mon-Fri
            out.append(cur)
        cur -= timedelta(days=1)
    out.reverse()
    return out


def _series(values: list[float], end: date | None = None) -> dict[date, float]:
    dates = _trading_dates(len(values), end=end)
    return dict(zip(dates, values, strict=True))


def _stub_fetch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returns: dict[uuid.UUID, dict[date, float]],
    return_type: str = "log",
) -> None:
    """Patch ``_fetch_returns_by_type`` on the service module.

    The service imports the function at module load, so patching on the
    service module (not on ``quant_queries``) is the correct surface.
    """
    str_keyed = {str(uid): obs for uid, obs in returns.items()}

    async def _fake(_db: Any, _ids: list[uuid.UUID], _start: date, _end: date) -> tuple:
        return str_keyed, return_type

    monkeypatch.setattr(cds, "_fetch_returns_by_type", _fake)


# ── D.1 — Perfect duplicates collapse to 1 ───────────────────────────


async def test_perfect_duplicates_collapse_to_single_representative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 instruments with identical return series → 1 cluster, 1 rep."""
    n = DEFAULT_WINDOW_DAYS
    same = [0.001 * ((i % 7) - 3) for i in range(n)]  # non-constant variance

    ids = [uuid.uuid4() for _ in range(5)]
    returns = {uid: _series(same) for uid in ids}
    _stub_fetch(monkeypatch, returns=returns)

    scores = {uid: 0.5 for uid in ids}

    result = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    assert isinstance(result, DedupResult)
    assert len(result.kept_ids) == 1, f"expected 1 kept, got {len(result.kept_ids)}"
    assert result.n_clusters == 1
    rep = result.kept_ids[0]
    # All five must map to the same cluster representative.
    for uid in ids:
        assert result.cluster_map[uid] == rep
    assert result.pair_corr_p95 > 0.99


# ── D.2 — Uncorrelated funds: all kept, n_clusters == n ──────────────


async def test_uncorrelated_funds_all_kept_as_distinct_clusters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(42)
    n = DEFAULT_WINDOW_DAYS
    ids = [uuid.uuid4() for _ in range(5)]
    # Independent gaussian-ish noise per fund
    returns = {
        uid: _series((rng.standard_normal(n) * 0.01).tolist())
        for uid in ids
    }
    _stub_fetch(monkeypatch, returns=returns)

    scores = {uid: 0.5 for uid in ids}
    result = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    assert len(result.kept_ids) == 5
    assert result.n_clusters == 5
    # Sanity: random series should have a well-behaved p95 below 0.5
    assert result.pair_corr_p95 < 0.7


# ── D.3 — Representative election by manager_score ───────────────────


async def test_representative_elected_by_highest_manager_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = DEFAULT_WINDOW_DAYS
    same = [0.001 * ((i % 7) - 3) for i in range(n)]

    ids = [uuid.uuid4() for _ in range(3)]
    returns = {uid: _series(same) for uid in ids}
    _stub_fetch(monkeypatch, returns=returns)

    scores = {ids[0]: 0.5, ids[1]: 0.9, ids[2]: 0.7}
    result = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    assert result.kept_ids == [ids[1]], "highest score (0.9) should win"

    # Now with None scores: surviving rep must be the one with a numeric score.
    scores_none = {ids[0]: None, ids[1]: 0.5, ids[2]: None}
    result2 = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores_none)  # type: ignore[arg-type]
    assert result2.kept_ids == [ids[1]]


# ── D.4 — Tiebreak determinism (UUID ASC) ────────────────────────────


async def test_tiebreak_is_deterministic_via_uuid_asc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = DEFAULT_WINDOW_DAYS
    same = [0.001 * ((i % 7) - 3) for i in range(n)]

    # Two identical funds with identical scores
    a, b = uuid.uuid4(), uuid.uuid4()
    ids = [a, b]
    returns = {a: _series(same), b: _series(same)}
    _stub_fetch(monkeypatch, returns=returns)

    scores = {a: 0.5, b: 0.5}

    result1 = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]
    result2 = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    assert result1.kept_ids == result2.kept_ids, "tiebreak must be deterministic"
    expected = sorted([a, b], key=str)[0]
    assert result1.kept_ids == [expected]


# ── D.5 — Threshold sensitivity ──────────────────────────────────────


async def test_threshold_sensitivity_clusters_only_above_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A≈B (ρ≈0.97) and C≈D (ρ≈0.88).

    threshold=0.95 → A&B cluster, C and D stay singletons (3 kept).
    threshold=0.85 → both pairs cluster (2 kept).
    """
    rng = np.random.default_rng(123)
    n = DEFAULT_WINDOW_DAYS
    base_ab = (rng.standard_normal(n) * 0.01).tolist()
    base_cd = (rng.standard_normal(n) * 0.01).tolist()

    a = base_ab
    b = [v + 0.0015 * rng.standard_normal() for v in base_ab]  # ρ≈0.97
    c = base_cd
    # Larger noise on D so ρ(C,D) lands ≈ 0.88
    d = [
        v + 0.005 * rng.standard_normal() + 0.001 * rng.standard_normal()
        for v in base_cd
    ]

    ids = [uuid.uuid4() for _ in range(4)]
    returns = {
        ids[0]: _series(a),
        ids[1]: _series(b),
        ids[2]: _series(c),
        ids[3]: _series(d),
    }
    _stub_fetch(monkeypatch, returns=returns)
    scores = {uid: 0.5 for uid in ids}

    strict = await dedup_correlated_funds(  # type: ignore[arg-type]
        db=None, fund_ids=ids, manager_scores=scores, threshold=0.95,
    )
    loose = await dedup_correlated_funds(  # type: ignore[arg-type]
        db=None, fund_ids=ids, manager_scores=scores, threshold=0.85,
    )

    # Strict cuts only the very-tight pair (A,B). C,D remain.
    assert len(strict.kept_ids) == 3
    # Loose merges both pairs.
    assert len(loose.kept_ids) == 2


# ── D.6 — Negative correlation collapses too ─────────────────────────


async def test_negative_correlation_treated_as_collinear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ρ = -0.99 is as colinear as +0.99 for Σ — must cluster together."""
    n = DEFAULT_WINDOW_DAYS
    base = [0.001 * ((i % 11) - 5) for i in range(n)]
    inverted = [-v for v in base]  # ρ exactly -1.0

    a, b = uuid.uuid4(), uuid.uuid4()
    ids = [a, b]
    returns = {a: _series(base), b: _series(inverted)}
    _stub_fetch(monkeypatch, returns=returns)
    scores = {a: 0.6, b: 0.7}

    result = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    # The two must share a cluster (abs(corr) > threshold).
    assert len(result.kept_ids) == 1
    assert result.kept_ids[0] == b  # higher score wins


# ── D.7 — Insufficient observations land in skipped_no_data ──────────


async def test_insufficient_observations_kept_as_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n_full = DEFAULT_WINDOW_DAYS
    n_short = MIN_OBSERVATIONS_FOR_DEDUP - 5  # below threshold

    same = [0.001 * ((i % 7) - 3) for i in range(n_full)]
    short = [0.001 * ((i % 5) - 2) for i in range(n_short)]

    long_a, long_b, short_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ids = [long_a, long_b, short_c]
    returns = {
        long_a: _series(same),
        long_b: _series(same),
        short_c: _series(short),
    }
    _stub_fetch(monkeypatch, returns=returns)
    scores = {long_a: 0.5, long_b: 0.6, short_c: 0.9}

    result = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    assert short_c in result.skipped_no_data
    # short_c stays as its own singleton even though its score is highest.
    assert short_c in result.kept_ids
    # long_a and long_b cluster — only one of them survives.
    survivors_long = {uid for uid in result.kept_ids if uid in (long_a, long_b)}
    assert len(survivors_long) == 1
    assert long_b in survivors_long  # higher score wins


# ── D.8 — Zero-variance column kept as singleton, no crash ───────────


async def test_zero_variance_column_treated_as_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = DEFAULT_WINDOW_DAYS
    constant = [0.0 for _ in range(n)]
    moving_a = [0.001 * ((i % 7) - 3) for i in range(n)]
    moving_b = [0.001 * ((i % 11) - 5) for i in range(n)]

    flat, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ids = [flat, a, b]
    returns = {flat: _series(constant), a: _series(moving_a), b: _series(moving_b)}
    _stub_fetch(monkeypatch, returns=returns)
    scores = {flat: 0.9, a: 0.5, b: 0.5}

    result = await dedup_correlated_funds(db=None, fund_ids=ids, manager_scores=scores)  # type: ignore[arg-type]

    # ``flat`` is zero-variance → singleton (in cluster_map mapped to itself).
    assert flat in result.kept_ids
    assert result.cluster_map[flat] == flat
    # No crash, no NaN escape — finite percentiles.
    assert np.isfinite(result.pair_corr_p50)
    assert np.isfinite(result.pair_corr_p95)


# ── D.9 — Integration: live DB universe lands in CLARABEL band ───────


@pytest.mark.integration
async def test_dedup_live_db_produces_tractable_universe() -> None:
    """Post-dedup cardinality lands in CLARABEL's feasible band.

    Hits the local docker-compose DB seeded for the test org. The test is
    intentionally defensive on environment errors — on Windows asyncpg
    can hit a Winsock SSL upgrade race even against a non-SSL local
    server. When the DB is unreachable for any OS/network reason we skip
    rather than fail so the service unit tests stay green.
    """
    from sqlalchemy import text as _t

    from app.core.db.engine import async_session_factory
    from app.domains.wealth.routes.model_portfolios import _load_universe_funds

    org_id = "403d8392-ebfa-5890-b740-45da49c556eb"

    try:
        async with async_session_factory() as db:
            await db.execute(
                _t("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": org_id},
            )
            universe = await _load_universe_funds(
                db, org_id, profile="moderate",
            )
    except (OSError, ConnectionError) as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"live DB unavailable: {type(exc).__name__}: {exc}")
    except Exception as exc:  # pragma: no cover - env-dependent
        # asyncpg wraps OS errors in its own exception hierarchy; also
        # SQLAlchemy DBAPIError. Catch broadly so environment noise never
        # fails the suite — the service logic is covered by D.1-D.8.
        if any(
            keyword in type(exc).__name__.lower()
            for keyword in ("connection", "operational", "interface", "timeout")
        ):
            pytest.skip(f"live DB unavailable: {type(exc).__name__}: {exc}")
        raise

    if not universe:
        pytest.skip("seeded org has empty post-prefilter universe")

    fund_ids = [uuid.UUID(f["instrument_id"]) for f in universe]
    scores: dict[uuid.UUID, float | None] = {
        uuid.UUID(f["instrument_id"]): (
            float(f["manager_score"]) if f.get("manager_score") is not None else None
        )
        for f in universe
    }

    try:
        async with async_session_factory() as db:
            await db.execute(
                _t("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": org_id},
            )
            result = await dedup_correlated_funds(db, fund_ids, scores)
    except (OSError, ConnectionError) as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"live DB unavailable mid-test: {type(exc).__name__}: {exc}")

    # Quant-architect's expected band per spec §A. Loose lower bound to 50
    # to absorb realistic seasonality of ingestion freshness.
    assert 50 <= len(result.kept_ids) <= 200, (
        f"Dedup produced {len(result.kept_ids)} funds "
        f"(input={result.n_input}, p50={result.pair_corr_p50:.3f}, "
        f"p95={result.pair_corr_p95:.3f}); expected 50-200"
    )
    assert 0.0 <= result.pair_corr_p50 <= 0.95
    assert result.pair_corr_p95 >= result.pair_corr_p50
    assert result.threshold_used == DEFAULT_CORR_THRESHOLD

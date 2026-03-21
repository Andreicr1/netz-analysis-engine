"""Tests for analytics route — Pareto async job + Redis cache."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from app.domains.wealth.routes.analytics import _hash_analytics_input

# ---------------------------------------------------------------------------
# Cache key stability
# ---------------------------------------------------------------------------


class TestHashAnalyticsInput:
    def test_same_inputs_same_hash(self):
        h1 = _hash_analytics_input(["A", "B"], [0.05, 0.03])
        h2 = _hash_analytics_input(["A", "B"], [0.05, 0.03])
        assert h1 == h2

    def test_order_invariant_blocks(self):
        h1 = _hash_analytics_input(["B", "A"], [0.05, 0.03])
        h2 = _hash_analytics_input(["A", "B"], [0.05, 0.03])
        assert h1 == h2, "block order should not affect hash (sorted internally)"

    def test_different_returns_different_hash(self):
        h1 = _hash_analytics_input(["A", "B"], [0.05, 0.03])
        h2 = _hash_analytics_input(["A", "B"], [0.05, 0.04])
        assert h1 != h2

    def test_hash_length(self):
        h = _hash_analytics_input(["X"], [0.1])
        assert len(h) == 24

    def test_includes_date_for_daily_invalidation(self):
        """Hash includes today's date, ensuring daily cache bust."""
        h = _hash_analytics_input(["A"], [0.1])
        # Rebuild expected payload
        payload = {
            "blocks": ["A"],
            "returns": [round(0.1, 8)],
            "date": date.today().isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True).encode()
        expected = hashlib.sha256(encoded).hexdigest()[:24]
        assert h == expected


# ---------------------------------------------------------------------------
# Schema: ParetoOptimizeResult with job_id
# ---------------------------------------------------------------------------


class TestParetoOptimizeResultSchema:
    def test_job_id_optional(self):
        from app.domains.wealth.schemas.analytics import ParetoOptimizeResult

        result = ParetoOptimizeResult(
            profile="moderate",
            recommended_weights={"A": 0.5},
            pareto_sharpe=[1.2],
            pareto_cvar=[-0.03],
            n_solutions=10,
            seed=42,
            input_hash="abc123",
            status="completed",
        )
        assert result.job_id is None

    def test_job_id_set(self):
        from app.domains.wealth.schemas.analytics import ParetoOptimizeResult

        result = ParetoOptimizeResult(
            profile="moderate",
            recommended_weights={},
            pareto_sharpe=[],
            pareto_cvar=[],
            n_solutions=0,
            seed=0,
            input_hash="",
            status="generating",
            job_id="abc-def-123",
        )
        assert result.job_id == "abc-def-123"
        assert result.status == "generating"

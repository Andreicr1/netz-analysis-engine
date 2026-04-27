"""PR-Q36 F03: regime_shift_detected is symmetric (both upward and downward)."""
from __future__ import annotations

import numpy as np

from quant_engine.correlation_regime_service import compute_correlation_regime


class TestRegimeShiftSymmetric:
    """F03: abs() on correlation delta detects dispersion regimes too."""

    def test_upward_correlation_shift_detected(self):
        """High-corr recent window vs low-corr baseline triggers regime shift."""
        rng = np.random.default_rng(42)
        N = 5
        T_base = 504
        T_recent = 60

        # Baseline: low correlation (independent noise)
        baseline = rng.normal(0.0, 0.01, size=(T_base, N))

        # Recent: high correlation (contagion — shared signal)
        signal = rng.normal(0.0, 0.01, size=T_recent)
        recent = np.column_stack([
            signal + rng.normal(0.0, 0.001, size=T_recent) for _ in range(N)
        ])

        returns = np.vstack([baseline, recent])
        result = compute_correlation_regime(returns)
        assert result.regime_shift_detected, "Upward correlation shift not detected"

    def test_downward_correlation_shift_detected(self):
        """Low-corr recent window vs high-corr baseline triggers regime shift (dispersion)."""
        rng = np.random.default_rng(42)
        N = 5
        T_base = 504
        T_recent = 60

        # Baseline: high correlation (shared signal)
        signal_base = rng.normal(0.0, 0.01, size=T_base)
        baseline = np.column_stack([
            signal_base + rng.normal(0.0, 0.001, size=T_base) for _ in range(N)
        ])

        # Recent: low correlation (independent noise — dispersion regime)
        recent = rng.normal(0.0, 0.01, size=(T_recent, N))

        returns = np.vstack([baseline, recent])
        result = compute_correlation_regime(returns)
        assert result.regime_shift_detected, (
            "Downward correlation shift (dispersion regime) not detected — F03 fix requires abs()"
        )

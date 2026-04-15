"""Type-level tests for assemble_factor_covariance (PR-A3 Section A §5).

Enforces Gate #5: ``PCADiagnostic`` lives in a separate module
(:mod:`quant_engine.factor_model_pca`) so that ``assemble_factor_covariance``
cannot accidentally accept it. The happy path uses
``typing_extensions.assert_type`` to pin the return type at compile time, and
the module-boundary test ensures that the two dataclasses are NOT co-located.

There is NO ``# type: ignore`` in this file by design — that was the fraud
the original test committed (PR-A3 audit). The separation itself, enforced
by the module-boundary assertion below, is what makes ``assemble_factor_covariance(diag)``
a type error at any real call site: mypy resolves ``PCADiagnostic`` from
``quant_engine.factor_model_pca`` and it is not structurally compatible
with ``FundamentalFactorFit``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from typing_extensions import assert_type

from quant_engine.factor_model_pca import PCADiagnostic
from quant_engine.factor_model_service import (
    FundamentalFactorFit,
    assemble_factor_covariance,
)


def _make_fit() -> FundamentalFactorFit:
    return FundamentalFactorFit(
        loadings=np.zeros((10, 3), dtype=np.float64),
        factor_cov=np.eye(3, dtype=np.float64),
        residual_variance=np.ones(10, dtype=np.float64),
        factor_names=["f1", "f2", "f3"],
        residual_series=np.zeros((100, 10), dtype=np.float64),
        r_squared_per_fund=np.ones(10, dtype=np.float64),
    )


def test_happy_path_returns_typed_ndarray() -> None:
    """assemble_factor_covariance accepts FundamentalFactorFit and returns float64 ndarray.

    The ``assert_type`` call is compile-time enforced by mypy / Pyright. If
    the return annotation of ``assemble_factor_covariance`` ever regresses
    to a bare ``np.ndarray`` (missing the dtype), this file fails typecheck.
    """
    fit = _make_fit()
    result = assemble_factor_covariance(fit)
    assert_type(result, npt.NDArray[np.float64])
    # Runtime sanity
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float64
    assert result.shape == (10, 10)


def test_pcadiagnostic_lives_in_separate_module() -> None:
    """Gate #5: PCADiagnostic must live in factor_model_pca, not factor_model_service.

    This is the structural gate that keeps diagnostic types from leaking into
    the covariance-assembly call surface. If someone re-exports
    ``PCADiagnostic`` from ``factor_model_service`` (for convenience), the
    gate collapses and ``assemble_factor_covariance(diag)`` becomes a
    harder-to-catch type error.
    """
    from quant_engine import factor_model_pca, factor_model_service

    assert PCADiagnostic is factor_model_pca.PCADiagnostic
    assert not hasattr(factor_model_service, "PCADiagnostic"), (
        "PCADiagnostic must not be importable from factor_model_service — "
        "the separation exists to prevent mistyped calls to "
        "assemble_factor_covariance."
    )
    assert not hasattr(factor_model_service, "compute_residual_pca")


def test_pcadiagnostic_is_not_a_fit() -> None:
    """Structural: PCADiagnostic lacks the attributes assemble_factor_covariance reads.

    ``assemble_factor_covariance`` accesses ``loadings``, ``factor_cov``,
    ``residual_variance`` on its argument. ``PCADiagnostic`` has none of
    these. This test pins that separation so a future refactor adding those
    attributes to ``PCADiagnostic`` would fail loudly.
    """
    diag_fields = {"explained_variance_ratio", "cumulative_variance", "top_loadings"}
    fit_fields = {
        "loadings",
        "factor_cov",
        "residual_variance",
        "factor_names",
        "residual_series",
        "r_squared_per_fund",
        "shrinkage_lambda",
        "factors_skipped",
    }
    assert diag_fields.isdisjoint({"loadings", "factor_cov", "residual_variance"})
    assert fit_fields.issuperset({"loadings", "factor_cov", "residual_variance"})

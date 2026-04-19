"""Unit tests for ``backend/scripts/bridge_mmf_catalog.py`` — PR-A26.3.3.

These cover the pure Python decision logic. The end-to-end DB run is
validated manually via the runbook (apply mode + second-pass refresh).
"""
from __future__ import annotations

from scripts.bridge_mmf_catalog import (
    DEFAULT_AUTO_THRESHOLD,
    DEFAULT_REVIEW_THRESHOLD,
    IuCandidate,
    SecMmfRow,
    _classify_best,
)


def _iu(name: str, iid: str = "00000000-0000-0000-0000-000000000001") -> IuCandidate:
    return IuCandidate(instrument_id=iid, name=name, current_series_id=None)


def _mmf(
    name: str, series: str = "S000001", cik: str = "1234567",
    category: str = "Government",
) -> SecMmfRow:
    return SecMmfRow(
        series_id=series, cik=cik, fund_name=name, mmf_category=category,
    )


class TestClassifyBest:
    def test_exact_match_auto_applies(self) -> None:
        iu = _iu("Fidelity Government Money Market Fund")
        mmfs = [
            _mmf("Fidelity Government Money Market Fund", "S000100"),
            _mmf("Vanguard Treasury MMF", "S000200"),
        ]
        m = _classify_best(
            iu, mmfs,
            auto_threshold=DEFAULT_AUTO_THRESHOLD,
            review_threshold=DEFAULT_REVIEW_THRESHOLD,
        )
        assert m is not None
        assert m.tier == "auto_applied"
        assert m.mmf.series_id == "S000100"
        assert m.score >= DEFAULT_AUTO_THRESHOLD

    def test_near_match_goes_to_review(self) -> None:
        iu = _iu("Vanguard Federal Money Market Fund")
        mmfs = [_mmf("Vanguard Federal Money Fund Inc", "S000101")]
        m = _classify_best(
            iu, mmfs,
            auto_threshold=DEFAULT_AUTO_THRESHOLD,
            review_threshold=DEFAULT_REVIEW_THRESHOLD,
        )
        assert m is not None
        # May go either way depending on exact score — assert it's bounded
        # and tier respects thresholds.
        assert m.score >= DEFAULT_REVIEW_THRESHOLD
        if m.score >= DEFAULT_AUTO_THRESHOLD:
            assert m.tier == "auto_applied"
        else:
            assert m.tier == "needs_review"

    def test_cross_family_not_bridged(self) -> None:
        iu = _iu("Vanguard Federal Money Market Fund")
        mmfs = [
            # Tax-exempt decoy with otherwise high token overlap.
            _mmf("Vanguard Tax-Exempt Money Market Fund",
                 "S000102", category="Exempt Government"),
        ]
        m = _classify_best(
            iu, mmfs,
            auto_threshold=DEFAULT_AUTO_THRESHOLD,
            review_threshold=DEFAULT_REVIEW_THRESHOLD,
        )
        assert m is None

    def test_below_review_discarded(self) -> None:
        iu = _iu("Vanguard Federal Money Market Fund")
        mmfs = [_mmf("BlackRock Prime Cash Portfolio", "S000103",
                     category="Prime")]
        m = _classify_best(
            iu, mmfs,
            auto_threshold=DEFAULT_AUTO_THRESHOLD,
            review_threshold=DEFAULT_REVIEW_THRESHOLD,
        )
        assert m is None

    def test_best_of_many(self) -> None:
        iu = _iu("Schwab Value Advantage Money Fund")
        mmfs = [
            _mmf("Fidelity Government MMF", "S000001"),
            _mmf("Schwab Value Advantage Money Fund", "S000777"),
            _mmf("Vanguard Prime MM", "S000002"),
        ]
        m = _classify_best(
            iu, mmfs,
            auto_threshold=DEFAULT_AUTO_THRESHOLD,
            review_threshold=DEFAULT_REVIEW_THRESHOLD,
        )
        assert m is not None
        assert m.mmf.series_id == "S000777"
        assert m.tier == "auto_applied"

    def test_empty_sec_universe(self) -> None:
        m = _classify_best(
            _iu("Anything Money Market"),
            [],
            auto_threshold=DEFAULT_AUTO_THRESHOLD,
            review_threshold=DEFAULT_REVIEW_THRESHOLD,
        )
        assert m is None

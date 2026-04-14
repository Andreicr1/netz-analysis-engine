"""Tests for universe sanitization worker.

Only the regex classification patterns are covered as unit tests —
integration coverage lives in the audit report script, which runs
post-migration against the real DB and samples excluded funds per
reason.

The sanitization module uses PostgreSQL POSIX regex word-boundary
markers (``\\m`` / ``\\M``) that Python's ``re`` module does not
understand natively. ``_to_python_re`` rewrites them so the intent of
the pattern can be validated in isolation.
"""
from __future__ import annotations

import re

import pytest

from app.domains.wealth.workers.universe_sanitization import (
    GAV_FLOOR_USD,
    PATTERN_CIT,
    PATTERN_EDUCATION,
    PATTERN_INSURANCE,
    PATTERN_RETIREMENT,
    PATTERN_SMA_WRAP,
    SANITIZATION_LOCK_ID,
)


def _to_python_re(pg_pattern: str) -> re.Pattern[str]:
    """Translate PostgreSQL ``\\m`` / ``\\M`` word boundaries to ``\\b``."""
    translated = pg_pattern.replace(r"\m", r"\b").replace(r"\M", r"\b")
    return re.compile(translated, re.IGNORECASE)


# ── Module-level constants ────────────────────────────────────────────


class TestModuleConstants:
    def test_lock_id_is_deterministic_literal(self) -> None:
        assert SANITIZATION_LOCK_ID == 900_063

    def test_gav_floor_is_three_billion(self) -> None:
        assert GAV_FLOOR_USD == 3_000_000_000


# ── Retirement pattern ────────────────────────────────────────────────


class TestRetirementPattern:
    PATTERN = _to_python_re(PATTERN_RETIREMENT)

    @pytest.mark.parametrize(
        "name",
        [
            "Vanguard Target Retirement 2045",
            "Fidelity 401(k) Plan Fund",
            "Fidelity 401k Growth",
            "JPMorgan 403(b) Stable Value",
            "Morgan Stanley IRA Portfolio",
            "American Funds SEP IRA",
            "Vanguard SIMPLE IRA",
            "ESOP Shares Trust",
            "Employee Stock Ownership Plan Fund",
            "ERISA Stable Value Fund",
            "State Street Target Date 2050",
            "BlackRock LifePath Retirement Fund",
            "Prudential Pension Plan Trust",
        ],
    )
    def test_matches_retirement_vehicle(self, name: str) -> None:
        assert self.PATTERN.search(name), f"expected match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "Goldman Sachs Large Cap Growth",
            "KKR Private Credit Fund",
            "Apollo European Equity",
            "Citadel Global Macro",
            "Blackstone Real Estate Income Trust",
            "Bridgewater All Weather",
        ],
    )
    def test_does_not_match_institutional(self, name: str) -> None:
        assert not self.PATTERN.search(name), f"unexpected match: {name}"


# ── CIT pattern ───────────────────────────────────────────────────────


class TestCitPattern:
    PATTERN = _to_python_re(PATTERN_CIT)

    @pytest.mark.parametrize(
        "name",
        [
            "JPMorgan Collective Investment Trust",
            "Wells Fargo Collective Trust",
            "Bank Collective Fund Series A",
            "T. Rowe Price Common Investment Fund",
            "Fidelity Collective Trust Growth",
        ],
    )
    def test_matches_cit(self, name: str) -> None:
        assert self.PATTERN.search(name), f"expected match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "Citadel Global Equities",
            "Private Credit Opportunities",
            "Ares Credit Strategies",
            "PIMCO Income Fund",
        ],
    )
    def test_does_not_match_non_cit(self, name: str) -> None:
        assert not self.PATTERN.search(name), f"unexpected match: {name}"


# ── Education pattern ─────────────────────────────────────────────────


class TestEducationPattern:
    PATTERN = _to_python_re(PATTERN_EDUCATION)

    @pytest.mark.parametrize(
        "name",
        [
            "Vanguard 529 Plan Moderate Portfolio",
            "Utah 529 Portfolio",
            "Coverdell ESA Fund",
            "Nuveen Education Savings Account",
        ],
    )
    def test_matches_education(self, name: str) -> None:
        assert self.PATTERN.search(name), f"expected match: {name}"

    @pytest.mark.parametrize(
        "name",
        ["Vanguard Value Index 529 Fund Holdings"],
    )
    def test_matches_529_even_without_plan_word(self, name: str) -> None:
        # 529 alone requires (plan|portfolio) adjacent — keep precision.
        assert not self.PATTERN.search(name)


# ── Insurance pattern ─────────────────────────────────────────────────


class TestInsurancePattern:
    PATTERN = _to_python_re(PATTERN_INSURANCE)

    @pytest.mark.parametrize(
        "name",
        [
            "Prudential Stable Value Fund",
            "MetLife Guaranteed Income Annuity",
            "Insurance-wrapped Income Strategy",
            "AIG GIC Portfolio",
            "Fixed Annuity Series Fund",
            "New York Life Guaranteed Interest Account",
        ],
    )
    def test_matches_insurance_wrapper(self, name: str) -> None:
        assert self.PATTERN.search(name), f"expected match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "Oaktree Value Opportunities",
            "Apollo Credit Strategies",
        ],
    )
    def test_does_not_match_generic_fund(self, name: str) -> None:
        assert not self.PATTERN.search(name), f"unexpected match: {name}"


# ── SMA / wrap pattern ────────────────────────────────────────────────


class TestSmaWrapPattern:
    PATTERN = _to_python_re(PATTERN_SMA_WRAP)

    @pytest.mark.parametrize(
        "name",
        [
            "Morgan Stanley SMA Program",
            "UBS Separately Managed Portfolio",
            "Merrill Wrap Account Series",
            "Fidelity Managed Account Program",
            "Schwab UMA Platform",
            "Wells Fargo Wrap Fee Account",
        ],
    )
    def test_matches_wrap_vehicle(self, name: str) -> None:
        assert self.PATTERN.search(name), f"expected match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "KKR Credit Opportunities",
            "Citadel Tactical Trading",
            "Bridgewater Pure Alpha",
        ],
    )
    def test_does_not_match_institutional_fund(self, name: str) -> None:
        assert not self.PATTERN.search(name), f"unexpected match: {name}"

"""Unit tests for the MMF fuzzy-bridge scorer (PR-A26.3.3 Section B)."""
from __future__ import annotations

import pytest

from app.domains.wealth.services.fuzzy_bridge import (
    score,
    verify_auto_match,
    _token_set,
)


class TestTokenSet:
    def test_stopwords_removed(self) -> None:
        tokens = _token_set("Vanguard Federal Money Market Fund")
        assert "vanguard" in tokens
        assert "federal" in tokens
        assert "fund" not in tokens
        assert "money" not in tokens
        assert "market" not in tokens

    def test_category_tokens_preserved(self) -> None:
        assert "government" in _token_set("Government Money Market")
        assert "prime" in _token_set("Prime Money Market")
        assert "tax" in _token_set("Tax-Exempt Money Market")
        assert "exempt" in _token_set("Tax Exempt Money Market")
        assert "municipal" in _token_set("Municipal Money Fund")
        assert "treasury" in _token_set("Treasury Only Fund")

    def test_empty_input(self) -> None:
        assert _token_set(None) == frozenset()
        assert _token_set("") == frozenset()


class TestScore:
    def test_exact_match_high(self) -> None:
        s = score("Vanguard Federal Money Market Fund", "Vanguard Federal Money Market Fund")
        assert s >= 0.95

    def test_minor_typo_still_matches(self) -> None:
        s = score("Fidelity Government Money Market Fund",
                  "Fidelity Government Money Mkt Fund")
        assert s >= 0.75

    def test_token_permutation_matches(self) -> None:
        s = score("Schwab Value Advantage Money Fund Inc",
                  "Value Advantage Money Fund — Schwab")
        assert s >= 0.80

    def test_cross_family_zeroed(self) -> None:
        # Govt MMF vs Tax-Exempt MMF must NOT bridge despite shared words.
        s = score("Vanguard Federal Money Market Fund",
                  "Vanguard Tax-Exempt Money Market Fund")
        assert s == 0.0

    def test_govt_vs_prime_zeroed(self) -> None:
        s = score("Fidelity Government Money Market",
                  "Fidelity Prime Money Market")
        assert s == 0.0

    def test_different_sponsors_low(self) -> None:
        # Same family (both Government) but different sponsor — must not clear 0.85.
        s = score("Vanguard Federal Money Market Fund",
                  "Schwab Government Money Market Fund")
        assert s < 0.85

    def test_empty_inputs_zero(self) -> None:
        assert score(None, "anything") == 0.0
        assert score("anything", None) == 0.0
        assert score("", "anything") == 0.0

    def test_no_category_claim_permissive(self) -> None:
        # Neither name makes a category claim — gate permits, score by overlap.
        s = score("Acme Liquidity Reserve Fund", "Acme Liquidity Reserve Fund")
        assert s >= 0.95


class TestVerifyAutoMatch:
    def test_verifies_genuine_high_score(self) -> None:
        name = "Fidelity Government Money Market Fund"
        ok, reason = verify_auto_match(name, name, score(name, name))
        assert ok
        assert reason == "ok"

    def test_rejects_below_threshold(self) -> None:
        ok, reason = verify_auto_match(
            "Vanguard Federal MMF", "Schwab Government MMF", 0.80,
        )
        assert not ok

    @pytest.mark.parametrize(
        "a,b",
        [
            ("Vanguard Federal MMF", "Vanguard Tax-Exempt MMF"),
        ],
    )
    def test_rejects_cross_family(self, a: str, b: str) -> None:
        ok, reason = verify_auto_match(a, b, 0.90)
        assert not ok
        assert "category" in reason or "jaccard" in reason or "seqmatch" in reason

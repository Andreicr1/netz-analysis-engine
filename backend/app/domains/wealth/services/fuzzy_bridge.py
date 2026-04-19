"""PR-A26.3.3 — deterministic fuzzy fund-name matching for MMF bridging.

Pure stdlib (``difflib`` + ``re``). No external dependencies, no ML.
Used by ``backend/scripts/bridge_mmf_catalog.py`` to bridge
``instruments_universe`` rows to ``sec_money_market_funds`` via
tokenized name similarity when the series_id bridge is missing.

Scoring combines two signals:

* Token-set Jaccard — robust to reordering and minor punctuation; weight 0.6.
* ``difflib.SequenceMatcher`` ratio — captures character-level similarity
  (typos, hyphenation, suffix differences); weight 0.4.

Stopword discipline is critical for MMFs: generic fund-jargon tokens
(``fund``, ``trust``, ``inc``, ``llc``, ``money``, ``market``, ``the``)
are stopworded because they appear in virtually every name. Category
qualifiers that DIFFERENTIATE funds (``government``, ``prime``,
``federal``, ``treasury``, ``tax``, ``exempt``, ``municipal``,
``retail``, ``institutional``) are NOT stopworded.

A category gate runs before scoring: if one name implies Tax-Exempt /
Municipal and the other implies Government / Treasury, the match is
hard-zeroed. Prevents Vanguard Federal Money Market from bridging to
Schwab Municipal Money Fund despite high token overlap.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Final

_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9]+")

# Generic fund-jargon tokens that add no discriminative signal.
# Keep this list tight; never add category qualifiers here.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "fund", "funds", "trust", "trusts",
        "inc", "llc", "lp", "ltd", "co", "corp", "corporation",
        "the", "a", "an", "of", "for", "and",
        "money", "market", "mmf", "mm",
        "class", "shares", "share",
        "series",
    },
)

# Category families used by the hard gate. A token's family is the key
# of the set it appears in; an empty family means "no category claim".
# Two names with different (non-empty) families produce score=0.0.
_GOVT_TOKENS: Final[frozenset[str]] = frozenset(
    {"government", "govt", "treasury", "federal", "gov"},
)
_TAX_EXEMPT_TOKENS: Final[frozenset[str]] = frozenset(
    {"tax", "exempt", "municipal", "muni", "taxexempt"},
)
_PRIME_TOKENS: Final[frozenset[str]] = frozenset({"prime"})


def _tokenize(name: str | None) -> list[str]:
    if not name:
        return []
    return [tok.lower() for tok in _TOKEN_RE.findall(name)]


def _token_set(name: str | None) -> frozenset[str]:
    """Lowercase tokens minus stopwords."""
    return frozenset(tok for tok in _tokenize(name) if tok not in _STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _seqmatch(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _family(tokens: frozenset[str]) -> str:
    """Single-label family derived from token membership.

    Returns one of ``'govt'``, ``'tax_exempt'``, ``'prime'``, or ``''``
    (no category claim). If a name carries tokens from multiple families
    (rare but e.g. "Government Prime Obligations"), we prefer tax_exempt
    > govt > prime for stricter gating.
    """
    if tokens & _TAX_EXEMPT_TOKENS:
        return "tax_exempt"
    if tokens & _GOVT_TOKENS:
        return "govt"
    if tokens & _PRIME_TOKENS:
        return "prime"
    return ""


def _category_gate_passes(a_tokens: frozenset[str], b_tokens: frozenset[str]) -> bool:
    """Hard filter: reject cross-family matches (govt ↔ tax_exempt, etc.).

    Empty family on either side is permissive — we only reject when both
    sides make explicit (and different) category claims.
    """
    fa = _family(a_tokens)
    fb = _family(b_tokens)
    if not fa or not fb:
        return True
    return fa == fb


def score(iu_name: str | None, sec_name: str | None) -> float:
    """Combined 0.0-1.0 similarity. Category mismatch → 0.0."""
    if not iu_name or not sec_name:
        return 0.0
    a_tokens = _token_set(iu_name)
    b_tokens = _token_set(sec_name)
    if not _category_gate_passes(a_tokens, b_tokens):
        return 0.0
    if not a_tokens or not b_tokens:
        return 0.0
    j = _jaccard(a_tokens, b_tokens)
    s = _seqmatch(iu_name, sec_name)
    return round(0.6 * j + 0.4 * s, 4)


def verify_auto_match(
    iu_name: str, sec_name: str, combined: float,
) -> tuple[bool, str]:
    """Second-pass verification gate for auto-applied matches.

    Returns ``(passed, reason)``. If ``passed`` is False, caller should
    downgrade the tier from ``auto_applied`` to ``needs_review``.

    Criteria (all must pass):
    * combined score >= 0.85
    * token-set Jaccard >= 0.70
    * SequenceMatcher ratio >= 0.80
    * same family (or both empty) — enforced again post-score for safety.
    """
    if combined < 0.85:
        return False, f"combined_score<{0.85:.2f}"
    a_tokens = _token_set(iu_name)
    b_tokens = _token_set(sec_name)
    if _jaccard(a_tokens, b_tokens) < 0.70:
        return False, "jaccard<0.70"
    if _seqmatch(iu_name, sec_name) < 0.80:
        return False, "seqmatch<0.80"
    if not _category_gate_passes(a_tokens, b_tokens):
        return False, "category_mismatch"
    return True, "ok"

"""Fund strategy classifier — cascade by signal authority.

Signal authority (highest → lowest):

    Tiingo description (Layer 1)  >  Fund name regex (Layer 2)  >  ADV brochure (Layer 3, separate)

Each classification carries a ``source`` tag for downstream audit/lineage.
Layer 3 (brochure) is NOT handled here — it needs DB access and is invoked
by the reclassification worker after Layers 1 and 2 fail.

Bug fixes vs. ``scripts/backfill_strategy_label.py`` (the legacy SQL classifier):

    1. ``\\bgold\\b`` with word boundary + negative lookahead — "Goldman" no
       longer classifies as Commodities/Precious Metals.
    2. Real Estate is matched BEFORE any ``income``/``mortgage``/``municipal``
       rule, so "iShares Mortgage Real Estate ETF", "Columbia Research
       Enhanced Real Estate ETF", and "PGIM Real Estate Income Fund" all
       land in Real Estate.
    3. Short / Inverse ETFs are detected and recursively classified against
       their underlying exposure (direction is preserved in ``matched_pattern``).
    4. ``allocation`` / ``balanced`` / ``multi-asset`` keywords in the fund
       name classify as Balanced — fixes "Credit Allocation Fund" being
       labelled as Credit.
    5. ``convertible`` only maps to Convertible Arbitrage when ``fund_type``
       is a hedge fund — fixes "AQR Innovation Convertible Opportunities"
       (a mutual fund) being labelled as an arb hedge strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ClassificationSource = Literal["tiingo_description", "name_regex", "adv_brochure", "fallback"]
ClassificationConfidence = Literal["high", "medium", "low"]

# Minimum description length to trust Layer 1. Empirically ~98% of Tiingo
# descriptions exceed 30 chars; anything shorter tends to be placeholder
# text ("short", "n/a", "--") that would mis-classify on sparse keywords.
_MIN_DESCRIPTION_CHARS = 30


@dataclass(frozen=True)
class ClassificationResult:
    """Tagged result of a single cascade pass."""

    strategy_label: str | None
    source: ClassificationSource
    confidence: ClassificationConfidence
    matched_pattern: str | None  # e.g., "desc:balanced:60_40" or "name:real_estate"


# Canonical strategy taxonomy. Exposed as a constant so callers (diff script,
# family map) can validate against a single source of truth.
STRATEGY_LABELS: frozenset[str] = frozenset(
    {
        # Equity — size × style
        "Large Blend", "Large Growth", "Large Value",
        "Mid Blend", "Mid Growth", "Mid Value",
        "Small Blend", "Small Growth", "Small Value",
        "International Equity", "Emerging Markets Equity",
        "Global Equity", "Sector Equity",
        # Equity — geographic / thematic (Round 2)
        "European Equity", "Asian Equity", "ESG/Sustainable Equity",
        # Fixed Income
        "Short-Term Bond", "Intermediate-Term Bond", "Long-Term Bond",
        "High Yield Bond", "Investment Grade Bond",
        "Government Bond", "Municipal Bond", "International Bond",
        "Inflation-Linked Bond",
        # Fixed Income — geographic / sector / thematic (Round 2)
        "European Bond", "Emerging Markets Debt", "ESG/Sustainable Bond",
        "Mortgage-Backed Securities", "Asset-Backed Securities",
        # Private / Alts
        "Private Credit", "Private Equity", "Venture Capital",
        "Real Estate", "Infrastructure", "Commodities", "Precious Metals",
        "Structured Credit",
        # Hedge
        "Long/Short Equity", "Global Macro", "Multi-Strategy",
        "Event-Driven", "Volatility Arbitrage", "Convertible Arbitrage",
        "Quant/Systematic",
        # Convertibles — non-hedge mutual fund variant (Round 2)
        "Convertible Securities",
        # Multi-Asset
        "Balanced", "Target Date", "Allocation",
        # Other
        "Cash Equivalent", "Other",
    },
)


def classify_fund(
    *,
    fund_name: str,
    fund_type: str | None,
    tiingo_description: str | None,
) -> ClassificationResult:
    """Run the cascade. Pure function; no DB access, no side effects.

    Returns the highest-authority classification that matches. If nothing
    matches (Layers 1 and 2 both miss), returns a ``fallback`` result with
    ``strategy_label=None`` so the caller can try Layer 3 (brochure) or
    leave the label unchanged.
    """
    # ── Layer 1: Tiingo description ─────────────────────────────────
    if tiingo_description and len(tiingo_description) >= _MIN_DESCRIPTION_CHARS:
        hit = _classify_from_description(tiingo_description, fund_type)
        if hit is not None:
            label, pattern = hit
            return ClassificationResult(
                strategy_label=label,
                source="tiingo_description",
                confidence="high",
                matched_pattern=pattern,
            )

    # ── Layer 2: Fund name regex (bug-fixed) ────────────────────────
    hit = _classify_from_name(fund_name, fund_type)
    if hit is not None:
        label, pattern = hit
        return ClassificationResult(
            strategy_label=label,
            source="name_regex",
            confidence="medium",
            matched_pattern=pattern,
        )

    # ── No match — caller decides whether to invoke Layer 3 ─────────
    return ClassificationResult(
        strategy_label=None,
        source="fallback",
        confidence="low",
        matched_pattern=None,
    )


# ───────────────────────────────────────────────────────────────────
# Layer 1 — Tiingo description
# ───────────────────────────────────────────────────────────────────

def _classify_from_description(
    description: str, fund_type: str | None,
) -> tuple[str, str] | None:
    """Match on prose hints in Tiingo's ``description`` field.

    Ordering matters. More specific composition hints (60/40, mortgage
    REIT) must run before broader keywords (``income``, ``real estate``)
    to avoid false positives.
    """
    text = description.lower()

    # ── Long/Short (Round 2 P1) — outside hedge gate (UCITS support) ─
    if re.search(
        r"long[/\s-]+short\s+(?:equit|strategy)|"
        r"long[/\s-]+short\s+position|"
        r"employs?\s+a\s+long[/\s-]+short",
        text,
    ):
        return ("Long/Short Equity", "desc:long_short")

    # ── Balanced / Multi-Asset (explicit composition) ───────────────
    # Catches "60% debt 40% equity", "approximately 50% stocks and 50% bonds".
    balanced_patterns = (
        r"(\d+)%\s+(?:of\s+its\s+(?:total\s+)?assets\s+in\s+)?(?:debt|bonds?|fixed\s+income)",
        r"(?:approximately|about)\s+\d+%.*(?:debt|bonds?).*\d+%.*(?:equit(?:y|ies)|stocks?)",
        r"\bbalanced\s+(?:fund|portfolio|strateg)",
        r"\btarget\s+(?:date|risk|allocation)",
    )
    for pattern in balanced_patterns:
        if re.search(pattern, text):
            if "target date" in text or "target retirement" in text:
                return ("Target Date", "desc:target_date")
            return ("Balanced", f"desc:balanced:{pattern[:40]}")

    # ── Real Estate / REIT ──────────────────────────────────────────
    real_estate_patterns = (
        r"\breal\s+estate\s+(?:securities|investment|sector|companies|stocks?)",
        r"\breits?\b",
        r"\breal\s+estate\s+investment\s+trusts?",
        r"\bmortgage\s+(?:reit|real\s+estate)",
    )
    for pattern in real_estate_patterns:
        if re.search(pattern, text):
            return ("Real Estate", f"desc:real_estate:{pattern[:40]}")

    # ── Precious Metals (specific — must precede Commodities) ───────
    precious_metals_patterns = (
        r"\bgold\s+(?:and\s+silver|mining|bullion|producers)",
        r"\bsilver\s+(?:mining|producers)",
        r"\bprecious\s+metals",
        r"\bmining\s+(?:companies|equities|stocks)",
    )
    for pattern in precious_metals_patterns:
        if re.search(pattern, text):
            return ("Precious Metals", f"desc:precious_metals:{pattern[:40]}")

    # ── Commodities (general) ───────────────────────────────────────
    commodity_patterns = (
        r"\bcommodit(?:y|ies)\s+(?:futures|index|prices|pool)",
        r"\bcrude\s+oil",
        r"\bagricultural\s+commodit",
        r"\bnatural\s+gas\s+(?:prices|futures)",
    )
    for pattern in commodity_patterns:
        if re.search(pattern, text):
            return ("Commodities", f"desc:commodities:{pattern[:40]}")

    # ── ESG / Sustainable (Round 2 P6) — runs before generic equity/bond ─
    if re.search(
        r"environmental.{0,15}social.{0,15}governance|"
        r"\besg\b|sustainable\s+invest|"
        r"impact\s+invest|socially\s+responsible",
        text,
    ):
        if re.search(r"\b(?:bond|fixed[- ]income|debt|credit)\b", text):
            return ("ESG/Sustainable Bond", "desc:esg_bond")
        if re.search(r"\b(?:equit|stocks?|shares?|companies)\b", text):
            return ("ESG/Sustainable Equity", "desc:esg_equity")
        return ("ESG/Sustainable Equity", "desc:esg_ambiguous")

    # ── Mortgage-Backed / Asset-Backed (Round 2 P4) — before Structured Credit ─
    if re.search(
        r"mortgage[- ]backed\s+secur|"
        r"\bmbs\b|\bcmbs\b|"
        r"agency\s+mortgage|residential\s+mortgage",
        text,
    ):
        return ("Mortgage-Backed Securities", "desc:mbs")
    if re.search(
        r"asset[- ]backed\s+secur|"
        r"(?:auto|credit\s+card|student\s+loan)[- ]backed",
        text,
    ):
        return ("Asset-Backed Securities", "desc:abs")

    # ── Standalone Convertible Securities (Round 2 P2) — non-hedge ──
    if re.search(r"invests?\s+.*convertible\s+(?:securities|bonds)", text):
        if not (fund_type and "hedge" in fund_type.lower()):
            return ("Convertible Securities", "desc:convertible_securities")

    # ── Structured Credit / CLO (specific — runs BEFORE Private Credit) ─
    if re.search(
        r"\bcollateralized\s+loan\s+obligation|"
        r"\bclos?\b|"
        r"\bcdos?\b|"
        r"securitized\s+credit|"
        r"structured\s+credit",
        text,
    ):
        return ("Structured Credit", "desc:clo")

    # ── Private Credit / Direct Lending ─────────────────────────────
    private_credit_patterns = (
        r"\bdirect\s+lending",
        r"\bprivate\s+(?:credit|debt|lending)",
        r"\bmiddle[- ]market\s+(?:loans|lending)",
        r"\bsenior\s+secured\s+loans",
    )
    for pattern in private_credit_patterns:
        if re.search(pattern, text):
            return ("Private Credit", f"desc:private_credit:{pattern[:40]}")

    # ── European bonds (Round 2 P7) — before generic Govt/IG/HY ────
    if re.search(
        r"(?:european|euro(?:pean|zone)|eu|germany|france|italy|spain|uk|united\s+kingdom)\s+"
        r"(?:government|sovereign|corporate)\s+(?:bond|debt|securit)",
        text,
    ):
        return ("European Bond", "desc:european_bond")

    # ── Emerging Markets Debt (Round 2 P8) — before EM Equity / IG Bond ─
    if re.search(
        r"emerging\s+market(?:s)?\s+(?:debt|bond|fixed[- ]income|sovereign|corporate\s+bond)",
        text,
    ):
        return ("Emerging Markets Debt", "desc:em_debt")

    # ── Fixed Income (specificity descending) ───────────────────────
    if re.search(r"\bhigh[- ]yield\s+bonds?|\bjunk\s+bonds?|\bnon[- ]investment\s+grade", text):
        return ("High Yield Bond", "desc:high_yield")
    if re.search(
        r"\bmunicipal\s+bonds?|\bmuni\s+(?:bonds?|debt)|"
        r"\btax[- ](?:exempt|free)",
        text,
    ):
        return ("Municipal Bond", "desc:municipal")
    if re.search(
        r"\btreasury\s+(?:bonds?|notes?|securities)|"
        r"\bgovernment\s+(?:bonds?|securities|obligations|debt)|"
        r"\bus\s+government\b|\bu\.s\.\s+government\b",
        text,
    ):
        return ("Government Bond", "desc:government_bond")
    if re.search(r"\binvestment[- ]grade\s+(?:bonds?|credit|debt)|\bcorporate\s+bonds?", text):
        return ("Investment Grade Bond", "desc:ig_bond")
    if re.search(r"\binflation[- ]linked|\btreasury\s+inflation|\btips\b", text):
        return ("Inflation-Linked Bond", "desc:tips")

    # ── Sector Equity (Round 2 P3) — before size×style ─────────────
    sector_desc_re = (
        r"invests?\s+(?:primarily|at\s+least\s+\d+%)\s+.*"
        r"(?:energy|health\s*care|technology|financial|utilit|"
        r"consumer|industrial|material|telecom)\s+(?:sector|compan|stocks|equit)"
    )
    if re.search(sector_desc_re, text):
        return ("Sector Equity", "desc:sector_equity")

    # ── European equity (Round 2 P7) — before International ────────
    if re.search(
        r"(?:european|euro(?:pean|zone)|eu)\s+(?:equit|stocks?|compan|shares?)|"
        r"(?:germany|france|italy|spain|uk|united\s+kingdom)\s+(?:equit|compan|stocks?)",
        text,
    ):
        return ("European Equity", "desc:european_equity")

    # ── Asian equity (Round 2 P8) — before International ───────────
    if re.search(
        r"\basia(?:n|[- ]pacific)?\s+(?:equit|stocks?|compan|shares?)|"
        r"\b(?:china|japan|korea|taiwan|singapore|hong\s+kong|india)\s+(?:equit|stocks?|compan)",
        text,
    ):
        return ("Asian Equity", "desc:asian_equity")

    # ── Equity (size × style, with international/EM override) ──────
    if re.search(r"\b(?:emerging\s+markets?|developing\s+countries)", text):
        return ("Emerging Markets Equity", "desc:emerging_markets")
    if re.search(r"\b(?:international|global|world|foreign)\s+(?:equit|stocks?|compan)", text):
        return ("International Equity", "desc:international")

    is_large = bool(re.search(r"\blarge[- ]cap|\bs&p\s*500|\brussell\s*1000|\blarge\s+compan", text))
    is_mid = bool(re.search(r"\bmid[- ]cap|\brussell\s*midcap|\bmedium\s+compan", text))
    is_small = bool(re.search(r"\bsmall[- ]cap|\brussell\s*2000|\bsmall\s+compan", text))
    is_growth = bool(re.search(r"\bgrowth\s+(?:stocks?|compan|style|invest)", text))
    is_value = bool(re.search(r"\bvalue\s+(?:stocks?|compan|style|invest)", text))

    if is_large:
        if is_growth:
            return ("Large Growth", "desc:large_growth")
        if is_value:
            return ("Large Value", "desc:large_value")
        return ("Large Blend", "desc:large_blend")
    if is_mid:
        if is_growth:
            return ("Mid Growth", "desc:mid_growth")
        if is_value:
            return ("Mid Value", "desc:mid_value")
        return ("Mid Blend", "desc:mid_blend")
    if is_small:
        if is_growth:
            return ("Small Growth", "desc:small_growth")
        if is_value:
            return ("Small Value", "desc:small_value")
        return ("Small Blend", "desc:small_blend")

    # ── Hedge strategies (gated on fund_type) ───────────────────────
    if fund_type and "hedge" in fund_type.lower():
        if re.search(r"\blong[/-]short|\b130[/-]30", text):
            return ("Long/Short Equity", "desc:long_short")
        if re.search(r"\bglobal\s+macro", text):
            return ("Global Macro", "desc:macro")
        if re.search(r"\bmulti[- ]strateg|\bmulti[- ]manager", text):
            return ("Multi-Strategy", "desc:multi_strategy")
        if re.search(r"\bevent[- ]driven|\bmerger\s+arbitrage|\bactivist", text):
            return ("Event-Driven", "desc:event_driven")
        if re.search(r"\bvolatility\s+(?:arbitrage|strategy)|\boptions\s+(?:strategy|based)", text):
            return ("Volatility Arbitrage", "desc:vol_arb")
        if re.search(r"\bquant(?:itative)?|\bsystematic|\balgorithmic", text):
            return ("Quant/Systematic", "desc:quant")

    # ── Cash / Money Market ─────────────────────────────────────────
    if re.search(r"\bmoney\s+market|\bcash\s+equivalent|\bshort[- ]duration", text):
        return ("Cash Equivalent", "desc:cash")

    return None


# ───────────────────────────────────────────────────────────────────
# Layer 2 — Fund name regex (bug-fixed)
# ───────────────────────────────────────────────────────────────────

def _classify_from_name(
    fund_name: str, fund_type: str | None,
) -> tuple[str, str] | None:
    """Match on the fund name alone.

    Bug fixes vs. legacy SQL classifier are documented at module top.
    Order matters — patterns are arranged so that higher-authority cues
    (explicit asset-class words) always run before lower-authority ones
    (generic suffixes like ``income`` or ``fund``).
    """
    if not fund_name:
        return None
    name = fund_name.lower()

    # Bug fix #1: word-boundary ``gold`` + negative lookahead for "goldman".
    has_gold = bool(re.search(r"\bgold\b(?!\s*man)", name))
    has_silver_mining = bool(re.search(r"\bsilver\b|\bmining\b|\bprecious\s+metal", name))

    # Round 2 P1: Long/Short detection OUTSIDE hedge gate (UCITS/mutual funds
    # named "Long Short Global Equity" must classify even when fund_type is
    # not "Hedge Fund"). Allow space, slash, or hyphen as separator.
    if re.search(r"\blong[\s/-]+short\b", name):
        return ("Long/Short Equity", "name:long_short_ucits_or_hedge")

    # Round 2 P5: Long-leverage ETFs (2x, 3x, ultra, daily bull). Strip the
    # leverage keyword and recurse on underlying. Excludes "ultra short"
    # (handled by inverse block below). Lineage carries `leveraged:` prefix.
    if re.search(
        r"\b(?:2x|3x|ultra(?!\s+short)|daily\s+(?:bull|long))\b",
        name,
    ):
        stripped = re.sub(
            r"\b(?:2x|3x|ultra(?!\s+short)|daily\s+(?:bull|long))\b",
            "",
            name,
        ).strip()
        if stripped and stripped != name:
            sub = _classify_from_name(stripped, fund_type)
            if sub is not None:
                return (sub[0], f"name:leveraged:{sub[1]}")

    # Bug fix #3: Short / Inverse FIRST — strip the direction prefix and
    # recurse on the underlying exposure. Must run BEFORE Real Estate so
    # that "ProShares Short Real Estate" carries the ``short`` lineage
    # even though its underlying is Real Estate.
    if re.search(r"\bshort\b|\binverse\b|-[123]x\b", name):
        stripped = re.sub(
            r"\b(?:short|inverse|ultra\s*short|-?[123]x)\b",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()
        if stripped and stripped != name:
            # Recurse. Returns None if the underlying also has no clue.
            sub = _classify_from_name(stripped, fund_type)
            if sub is not None:
                return (sub[0], f"name:short:{sub[1]}")

    # Structured Credit / CLO — check by name regardless of fund_type.
    # Runs before Real Estate / FI so "CLO" funds don't leak into bond buckets.
    if re.search(r"\bclos?\b|\bcollateralized\s+loan", name):
        return ("Structured Credit", "name:clo")

    # Round 2 P4: Mortgage-Backed / Asset-Backed Securities — BEFORE Real
    # Estate so "PIMCO Mortgage-Backed Securities" doesn't fall into Real
    # Estate via "mortgage". Pattern is strict: requires "mortgage-backed"
    # or "MBS/CMBS" — does NOT match "Mortgage Real Estate ETF".
    if re.search(
        r"mortgage[- ]backed|"
        r"\bmbs\s+(?:fund|portfolio|strateg)|"
        r"\bcmbs\b|"
        r"(?:agency|residential|commercial)\s+mortgage\s+(?:secur|bond)",
        name,
    ):
        return ("Mortgage-Backed Securities", "name:mbs")
    if re.search(
        r"asset[- ]backed\s+secur|"
        r"\babs\s+(?:fund|portfolio|strateg)|"
        r"(?:auto|consumer)[- ]backed\s+loan",
        name,
    ):
        return ("Asset-Backed Securities", "name:abs")

    # Bug fix #2: Real Estate BEFORE Fixed Income / Income / Municipal.
    if re.search(r"\breal\s+estate\b|\breit\b|\bhousing\b|\bresidential\b", name):
        return ("Real Estate", "name:real_estate")

    # Bug fix #4: Balanced / Multi-Asset keywords.
    # "Credit Allocation Funds" must be Balanced, not Credit.
    if re.search(r"\ballocation\b|\bbalanced\b|\bmulti[- ]asset\b", name):
        return ("Balanced", "name:balanced")
    if re.search(r"\btarget\s+(?:date|retirement|\d{4})", name):
        return ("Target Date", "name:target_date")

    # Round 2 P6: ESG / Sustainable — before Precious Metals / size×style.
    # Distinguish bond vs equity ESG by presence of bond keyword in name.
    if re.search(
        r"\b(?:esg|sustainable|sustainability|responsible\s+invest|sri|impact)\b",
        name,
    ):
        if re.search(r"\b(?:bond|fixed[- ]income|debt|credit)\b", name):
            return ("ESG/Sustainable Bond", "name:esg_bond")
        return ("ESG/Sustainable Equity", "name:esg_equity")

    # Precious Metals (uses the word-boundary ``gold`` boolean above).
    if has_gold or has_silver_mining:
        return ("Precious Metals", "name:precious_metals")

    # Private Credit / Direct Lending.
    if re.search(r"\bdirect\s+lend|\bprivate\s+(?:credit|debt|lending)|\bmiddle[- ]market", name):
        return ("Private Credit", "name:private_credit")

    # Round 2 P2: Standalone Convertible Securities (non-hedge mutual funds).
    # Must run BEFORE the hedge-gated Convertible Arbitrage so non-hedge
    # funds with "Convertible Securities/Bond/Fund" in name get the right label.
    if re.search(r"\bconvertible\s+(?:secur|bond|fund)", name):
        if not (fund_type and "hedge" in fund_type.lower()):
            return ("Convertible Securities", "name:convertible_securities")

    # Bug fix #5: Convertible is only Convertible Arbitrage when the fund
    # is actually a hedge fund. A mutual fund called "Convertible
    # Opportunities" is an equity fund, not an arb strategy.
    if "convertible" in name and fund_type and "hedge" in fund_type.lower():
        return ("Convertible Arbitrage", "name:convertible_arb")

    # Round 2 P7: European Bond — before generic Govt/IG/HY.
    if re.search(
        r"\beuropean\s+(?:bond|fixed|debt|credit|sovereign|corporate)",
        name,
    ):
        return ("European Bond", "name:european_bond")

    # Round 2 P8: Emerging Markets Debt — before generic IG/HY.
    if re.search(
        r"emerging\s+market(?:s)?\s+(?:debt|bond|fixed|sovereign|corporate)|"
        r"\bem\s+(?:debt|bond|sovereign)",
        name,
    ):
        return ("Emerging Markets Debt", "name:em_debt")

    # Fixed Income (after Real Estate).
    if re.search(r"\bhigh[- ]yield\b|\bjunk\b", name):
        return ("High Yield Bond", "name:high_yield")
    if re.search(r"\bmunicipal\b|\bmuni\b|\btax[- ](?:exempt|free)", name):
        return ("Municipal Bond", "name:municipal")
    if re.search(
        r"\btreasury\b|"
        r"\bgovernment\s+(?:bond|fund|securities|obligations|portfolio)",
        name,
    ):
        return ("Government Bond", "name:government")
    if re.search(r"\binvestment[- ]grade\b|\bcorporate\s+bond", name):
        return ("Investment Grade Bond", "name:ig_bond")
    if re.search(r"\btips\b|\binflation[- ]linked", name):
        return ("Inflation-Linked Bond", "name:tips")
    # Generic bond / income — lowest priority in FI. Must NOT catch
    # equity funds that happen to carry "income" in the name; we require
    # "equity" to be absent.
    if re.search(r"\bbond\b|\bincome\b|\bfixed[- ]income\b", name) and "equity" not in name:
        return ("Intermediate-Term Bond", "name:general_bond")

    # Private fund defaults from fund_type alone. Must run BEFORE the public
    # equity heuristics (international / size / style) so that names like
    # "Apollo Global Private Equity Secondaries Fund" are not hijacked by the
    # `\bglobal\b` → International Equity rule. For ADV-reported private
    # funds, fund_type is the authoritative signal.
    if fund_type:
        ft = fund_type.lower()
        if "private equity" in ft:
            if re.search(r"\bsecondar(?:y|ies)\b", name):
                return ("Private Equity", "name:pe_secondaries")
            if re.search(r"\bco[- ]invest", name):
                return ("Private Equity", "name:pe_coinvest")
            if re.search(r"\bgrowth\s+equit", name):
                return ("Private Equity", "name:pe_growth")
            if re.search(r"\binfrastructure", name):
                return ("Infrastructure", "name:pe_infra")
            return ("Private Equity", "fund_type:pe")
        if "venture" in ft:
            return ("Venture Capital", "fund_type:vc")
        if "real estate" in ft:
            return ("Real Estate", "fund_type:re")
        if "securitized" in ft:
            if re.search(r"\bclos?\b|\bcollateralized\s+loan", name):
                return ("Structured Credit", "name:clo")
            return ("Private Credit", "fund_type:securitized")

    # Round 2 P3: Sector Equity — before EM/International/size×style.
    sector_patterns = (
        (r"\b(?:energy|oil\s+&\s+gas|petroleum)\s+(?:sector|fund|etf|portfolio|equities|stocks?)", "energy"),
        (r"\b(?:health\s*care|biotech|pharmaceutical|medical)\b", "healthcare"),
        (r"\b(?:technology|tech\s+sector|software|semiconductor)\b", "technology"),
        (r"\b(?:financials?|bank(?:ing)?\s+sector|insurance\s+sector)\b", "financials"),
        (r"\b(?:utilit|infrastructure\s+equity)", "utilities"),
        (r"\b(?:consumer\s+(?:discretion|staples)|retail\s+sector)", "consumer"),
        (r"\b(?:industrial(?:s)?|transportation|aerospace)\b", "industrials"),
        (r"\b(?:materials\s+sector|chemicals\s+equity|metals\s+&\s+mining)", "materials"),
        (r"\b(?:communic|media\s+sector|telecom)", "communications"),
    )
    for pattern, sector_name in sector_patterns:
        if re.search(pattern, name):
            return ("Sector Equity", f"name:sector:{sector_name}")

    # Round 2 P7: European Equity — before International.
    if re.search(
        r"\beuropean\s+(?:equit|stock|company|compan|share)|"
        r"\beuro(?:pean|zone)\s+(?:equit|stock|index)|"
        r"\beuro\s*stoxx\b",
        name,
    ):
        return ("European Equity", "name:european_equity")

    # Round 2 P8: Asian Equity — before International. Country word + any
    # equity-flavored keyword (equit/stock/compan/fund/portfolio/growth/value/
    # smaller). Skips if name has a clear bond/debt context.
    asian_country_re = (
        r"\b(?:asia(?:n|[- ]pacific)?|china|japan|korea|taiwan|"
        r"singapore|hong\s+kong|india)\b"
    )
    if re.search(asian_country_re, name):
        if not re.search(r"\bbond\b|\bdebt\b|\bfixed[- ]income\b|\bsovereign\b", name):
            if re.search(
                r"\b(?:equit|stock|compan|fund|portfolio|index|growth|value|smaller)\b",
                name,
            ):
                return ("Asian Equity", "name:asian_equity")

    # Equity size × style.
    if re.search(r"\bemerging\s+markets?", name):
        return ("Emerging Markets Equity", "name:emerging")
    if re.search(r"\binternational\b|\bglobal\b|\bworld\b|\bforeign\b", name):
        return ("International Equity", "name:international")

    is_large = bool(re.search(r"\blarge[- ]cap\b|\bs&p\s*500", name))
    is_mid = bool(re.search(r"\bmid[- ]cap\b", name))
    is_small = bool(re.search(r"\bsmall[- ]cap\b|\brussell\s*2000", name))
    is_growth = bool(re.search(r"\bgrowth\b", name))
    is_value = bool(re.search(r"\bvalue\b", name))

    if is_large:
        if is_growth:
            return ("Large Growth", "name:large_growth")
        if is_value:
            return ("Large Value", "name:large_value")
        return ("Large Blend", "name:large_blend")
    if is_mid:
        if is_growth:
            return ("Mid Growth", "name:mid_growth")
        if is_value:
            return ("Mid Value", "name:mid_value")
        return ("Mid Blend", "name:mid_blend")
    if is_small:
        if is_growth:
            return ("Small Growth", "name:small_growth")
        if is_value:
            return ("Small Value", "name:small_value")
        return ("Small Blend", "name:small_blend")

    # Style without size → default to Large (most common for retail funds).
    # Catches "Vanguard Selected Value", "Dodge & Cox Growth", etc.
    if is_growth:
        return ("Large Growth", "name:style_only_growth")
    if is_value:
        return ("Large Value", "name:style_only_value")

    # Hedge strategies — gated on fund_type.
    if fund_type and "hedge" in fund_type.lower():
        if re.search(r"\blong[/-]short", name):
            return ("Long/Short Equity", "name:long_short")
        if re.search(r"\bmacro\b", name):
            return ("Global Macro", "name:macro")
        if re.search(r"\bmulti[- ]strateg", name):
            return ("Multi-Strategy", "name:multi_strategy")
        if re.search(r"\bevent[- ]driven|\bmerger\s+arb|\bactivist", name):
            return ("Event-Driven", "name:event_driven")
        if re.search(r"\bvolatility\b", name):
            return ("Volatility Arbitrage", "name:vol_arb")
        if re.search(r"\bquant\b|\bsystematic", name):
            return ("Quant/Systematic", "name:quant")
        return ("Multi-Strategy", "name:hedge_generic")

    return None

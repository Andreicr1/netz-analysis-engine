/**
 * Institutional label dictionary — Risk Methodology v3.
 *
 * Canonical frontend source of truth for translating raw quant jargon
 * (CVaR, GARCH, EWMA, CFNAI, regime enums, drawdown, DTW drift, parametric
 * stress scenarios) into the institutional phrasing that user-facing
 * surfaces render.
 *
 * Both wealth and terminal frontends consume this module. The wealth path
 * ``frontends/wealth/src/lib/i18n/quant-labels.ts`` is a re-export shim;
 * do not duplicate keys there.
 *
 * Pairs with the backend dictionary in
 * ``backend/app/domains/wealth/schemas/sanitized.py`` (METRIC_LABELS,
 * REGIME_LABELS, EVENT_TYPE_LABELS). Drift is enforced at CI by
 * ``backend/tests/wealth/test_sanitization_parity.py``: every backend
 * METRIC_LABELS key MUST be representable here.
 *
 * Scope of v3
 * -----------
 *   Quant key                           →  Institutional label
 *   ------------------------------------ -----------------------------
 *   CVaR / Expected Shortfall           →  Conditional Tail Risk (CVaR 95%)
 *   Regime                              →  Market Regime: Expansion / Cautious / Stress
 *   GARCH / EWMA Volatility             →  Conditional Volatility
 *   CFNAI / Macro Score                 →  Real Economy Activity Index
 *   Drawdown                            →  Maximum Drawdown
 *   DTW drift                           →  Strategy Deviation Score
 *   Parametric scenarios                →  GFC 2008 / COVID 2020 / Taper 2013 / Rate Shock 200bps
 *
 * Backend regime labels (RISK_ON / RISK_OFF / CRISIS) are translated by
 * ``regimeLabel()`` to the three-state institutional phrasing
 * (Expansion / Cautious / Stress).
 *
 * Consumers
 * ---------
 *   import {
 *       humanizeMetric,
 *       regimeLabel,
 *       scenarioLabel,
 *       profileDisplayLabel,
 *   } from "@investintell/ii-terminal-core/i18n/quant-labels";
 *
 * Adding a new label
 * ------------------
 * 1. Add the canonical quant key to ``QuantMetricKey``.
 * 2. Add the institutional phrasing to ``METRIC_LABELS``.
 * 3. If the key has alternate spellings (e.g. ``cvar_95``, ``cvar95``,
 *    ``expected_shortfall``), route them through ``humanizeMetric``'s
 *    ``normalise`` branch — never add alternate keys as top-level
 *    entries.
 * 4. Add the same key to backend ``METRIC_LABELS`` so the parity test
 *    passes.
 */

export type QuantMetricKey =
	| "cvar_95"
	| "cvar_95_1m"
	| "cvar_95_3m"
	| "cvar_95_6m"
	| "cvar_95_12m"
	| "cvar_95_conditional"
	| "expected_shortfall"
	| "regime"
	| "garch_volatility"
	| "ewma_volatility"
	| "cfnai"
	| "macro_score"
	| "drawdown"
	| "max_drawdown"
	| "max_drawdown_1y"
	| "max_drawdown_3y"
	| "dtw_drift_score";

const METRIC_LABELS: Readonly<Record<QuantMetricKey, string>> = {
	cvar_95: "Conditional Tail Risk (CVaR 95%)",
	cvar_95_1m: "Conditional Tail Risk (CVaR 95%) — 1M",
	cvar_95_3m: "Conditional Tail Risk (CVaR 95%) — 3M",
	cvar_95_6m: "Conditional Tail Risk (CVaR 95%) — 6M",
	cvar_95_12m: "Conditional Tail Risk (CVaR 95%) — 12M",
	cvar_95_conditional: "Conditional Tail Risk (CVaR 95%) — Regime-conditioned",
	expected_shortfall: "Conditional Tail Risk (CVaR 95%)",
	regime: "Market Regime",
	garch_volatility: "Conditional Volatility",
	ewma_volatility: "Conditional Volatility",
	cfnai: "Real Economy Activity Index",
	macro_score: "Real Economy Activity Index",
	drawdown: "Maximum Drawdown",
	max_drawdown: "Maximum Drawdown",
	max_drawdown_1y: "Maximum Drawdown (1Y)",
	max_drawdown_3y: "Maximum Drawdown (3Y)",
	dtw_drift_score: "Strategy Deviation Score",
};

/**
 * Normalise an incoming metric key to the canonical QuantMetricKey.
 * Accepts snake_case, camelCase, SCREAMING, hyphenated, and a few
 * well-known aliases. Returns ``null`` for unknown keys so callers can
 * fall back to the raw string if they prefer.
 */
function normalise(raw: string): QuantMetricKey | null {
	const k = raw.trim().toLowerCase().replace(/[-\s]+/g, "_");
	switch (k) {
		case "cvar":
		case "cvar95":
		case "cvar_95":
		case "c_var_95":
		case "conditional_value_at_risk":
		case "expected_shortfall":
		case "es":
			return "cvar_95";
		case "cvar_95_1m":
			return "cvar_95_1m";
		case "cvar_95_3m":
			return "cvar_95_3m";
		case "cvar_95_6m":
			return "cvar_95_6m";
		case "cvar_95_12m":
			return "cvar_95_12m";
		case "cvar_95_conditional":
		case "volatility_garch":
			// volatility_garch is the DB column name (migration 0058) — same
			// concept as garch_volatility in this dictionary.
			return k === "volatility_garch" ? "garch_volatility" : "cvar_95_conditional";
		case "regime":
		case "market_regime":
			return "regime";
		case "garch":
		case "garch_vol":
		case "garch_volatility":
			return "garch_volatility";
		case "ewma":
		case "ewma_vol":
		case "ewma_volatility":
			return "ewma_volatility";
		case "cfnai":
			return "cfnai";
		case "macro_score":
		case "macroscore":
			return "macro_score";
		case "drawdown":
			return "drawdown";
		case "max_drawdown":
		case "maxdrawdown":
		case "maximum_drawdown":
			return "max_drawdown";
		case "max_drawdown_1y":
			return "max_drawdown_1y";
		case "max_drawdown_3y":
			return "max_drawdown_3y";
		case "dtw_drift":
		case "dtw_drift_score":
			return "dtw_drift_score";
		default:
			return null;
	}
}

/**
 * Translate a raw quant metric key into its institutional label.
 * Unknown keys fall through to the input string so ad-hoc metrics keep
 * rendering — never silently hide a field from the user.
 */
export function humanizeMetric(raw: string): string {
	const key = normalise(raw);
	if (key && METRIC_LABELS[key]) return METRIC_LABELS[key];
	return raw;
}

/**
 * Regime label translation — Risk Methodology v3 tri-state phrasing.
 *
 * Backend emits uppercase enum (``RISK_ON`` / ``RISK_OFF`` / ``CRISIS``).
 * The institutional reading is Expansion (benign growth), Cautious
 * (late-cycle / mixed signals), and Stress (drawdown / crisis).
 * ``NEUTRAL`` is an intermediate state that maps to Cautious.
 *
 * Unknown labels pass through unchanged so a new backend regime
 * (e.g. ``STAGFLATION``) is visible rather than silently relabelled.
 */
export function regimeLabel(raw: string | null | undefined): string {
	if (!raw) return "—";
	const k = raw.trim().toUpperCase();
	switch (k) {
		case "RISK_ON":
		case "EXPANSION":
			return "Expansion";
		case "NEUTRAL":
		case "RISK_OFF":
		case "CAUTIOUS":
			return "Cautious";
		case "CRISIS":
		case "STRESS":
			return "Stress";
		default:
			return raw;
	}
}

/**
 * Fully-qualified header string for the market regime tri-state — used in
 * chart titles and section headings.
 */
export const MARKET_REGIME_HEADER = "Market Regime: Expansion / Cautious / Stress";

// ── Parametric stress scenarios ──────────────────────────────────────
//
// The four canonical parametric scenarios delivered by the construction
// engine's stress suite (``POST /stress-test``). Backend emits the slug;
// frontend renders the institutional label.

export type StressScenarioKey =
	| "gfc_2008"
	| "covid_2020"
	| "taper_2013"
	| "rate_shock_200bps";

const SCENARIO_LABELS: Readonly<Record<StressScenarioKey, string>> = {
	gfc_2008: "GFC 2008",
	covid_2020: "COVID 2020",
	taper_2013: "Taper Tantrum 2013",
	rate_shock_200bps: "Rate Shock +200bps",
};

/**
 * Translate a parametric stress scenario slug to its institutional label.
 * Unknown keys (e.g. tenant-defined custom scenarios) fall through to a
 * title-cased version of the raw slug — never silently dropped.
 */
export function scenarioLabel(raw: string | null | undefined): string {
	if (!raw) return "—";
	const k = raw.trim().toLowerCase();
	if (k in SCENARIO_LABELS) {
		return SCENARIO_LABELS[k as StressScenarioKey];
	}
	// Fall through for custom scenarios — title-case the slug (replace
	// underscores with spaces, capitalise each word).
	return raw
		.split(/[_\s]+/)
		.filter(Boolean)
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

// ── PR-BE-7 — Profile display labels ─────────────────────────────────
//
// Slugs (``conservative`` / ``moderate`` / ``growth``) are stable in
// code, URL, and DB. Product copy ("Dynamic Growth" for ``growth``)
// flows through this helper so the marketing label stays decoupled
// from the persisted slug. ``aggressive`` is rewritten to ``growth``
// (sunset 2026-10-30, 180 days post-merge) — see PR-BE-7.
//
// Mirror of the Pydantic helper
// ``app.domains.wealth.schemas.sanitized.profile_display_label``.

type ProfileSlug = "conservative" | "moderate" | "growth";
type DisplayContext = "dense" | "full";

const PROFILE_DISPLAY: Readonly<Record<ProfileSlug, Record<DisplayContext, string>>> = {
	conservative: { dense: "Conservative", full: "Conservative" },
	moderate: { dense: "Moderate", full: "Moderate" },
	growth: { dense: "Dynamic", full: "Dynamic Growth" },
};

/**
 * Resolve a profile slug to its institutional display label.
 *
 * ``context="dense"`` yields the short form ("Dynamic"), used in
 * chips, badges, and tight chart legends. ``context="full"`` yields
 * the marketing name ("Dynamic Growth"), used in copy that has room
 * for the longer phrasing. ``conservative`` and ``moderate`` are
 * identical across contexts.
 *
 * Unknown slugs (e.g. tenant-scoped custom profiles introduced via
 * ConfigService in v2 / post-GA) fall through to a title-cased
 * version of the raw slug — never silently dropped.
 */
export function profileDisplayLabel(
	profile: string,
	context: DisplayContext = "full",
): string {
	const lc = profile.toLowerCase();
	const canonical = lc === "aggressive" ? "growth" : lc;
	if (canonical in PROFILE_DISPLAY) {
		return PROFILE_DISPLAY[canonical as ProfileSlug][context];
	}
	if (!profile) return profile;
	return profile.charAt(0).toUpperCase() + profile.slice(1);
}

// ── Introspection helpers (for parity test) ──────────────────────────
//
// These are exported so the backend parity test can introspect the
// canonical key set without parsing the source file. Frozen Maps so
// callers cannot mutate them.

/**
 * Canonical metric keys recognised by ``humanizeMetric``. Used by the
 * sanitization-parity test to assert backend keys ⊆ frontend keys.
 *
 * Includes both top-level ``METRIC_LABELS`` keys and the alternate
 * spellings handled by ``normalise`` — anything a backend producer can
 * emit and reasonably expect to be translated.
 */
export const RECOGNISED_METRIC_KEYS: ReadonlyArray<string> = Object.freeze([
	// Canonical keys (top-level METRIC_LABELS)
	...(Object.keys(METRIC_LABELS) as string[]),
	// Alternate spellings handled by normalise()
	"cvar",
	"cvar95",
	"c_var_95",
	"conditional_value_at_risk",
	"es",
	"market_regime",
	"garch",
	"garch_vol",
	"ewma",
	"ewma_vol",
	"macroscore",
	"maxdrawdown",
	"maximum_drawdown",
	"dtw_drift",
	"volatility_garch",
]);

/**
 * Canonical regime tokens recognised by ``regimeLabel``.
 */
export const RECOGNISED_REGIME_KEYS: ReadonlyArray<string> = Object.freeze([
	"RISK_ON",
	"EXPANSION",
	"NEUTRAL",
	"RISK_OFF",
	"CAUTIOUS",
	"CRISIS",
	"STRESS",
]);

/**
 * Canonical parametric scenario slugs recognised by ``scenarioLabel``.
 */
export const RECOGNISED_SCENARIO_KEYS: ReadonlyArray<string> = Object.freeze(
	Object.keys(SCENARIO_LABELS),
);

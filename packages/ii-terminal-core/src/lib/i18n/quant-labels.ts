/**
 * Institutional label dictionary — Risk Methodology v3.
 *
 * Surface-facing replacement for the raw quant jargon that flows out
 * of the backend risk engines (CVaR, Expected Shortfall, GARCH,
 * EWMA, CFNAI, regime labels, drawdown). The wealth frontend is
 * "dumb" by design — it never renders a bare model identifier to an
 * institutional allocator. Every metric shown to a user passes
 * through this dictionary first.
 *
 * Scope of v3
 * -----------
 * The mapping mirrors the Risk Methodology v3 reference and the
 * §3 UX charter:
 *
 *   Quant key                           →  Institutional label
 *   ------------------------------------ -----------------------------
 *   CVaR / Expected Shortfall           →  Conditional Tail Risk (CVaR 95%)
 *   Regime                              →  Market Regime: Expansion / Cautious / Stress
 *   GARCH / EWMA Volatility             →  Conditional Volatility
 *   CFNAI / Macro Score                 →  Real Economy Activity Index
 *   Drawdown                            →  Maximum Drawdown
 *
 * Backend regime labels (RISK_ON / RISK_OFF / CRISIS) are translated
 * by `regimeLabel()` to the three-state institutional phrasing
 * (Expansion / Cautious / Stress).
 *
 * Consumers
 * ---------
 *   import { humanizeMetric, regimeLabel } from "../i18n/quant-labels";
 *   <MetricCard label={humanizeMetric("cvar_95")} value={formatPercent(x)} />
 *   <span>{regimeLabel(store.regime.label)}</span>
 *
 * Adding a new label
 * ------------------
 * 1. Add the canonical quant key to `QuantMetricKey`.
 * 2. Add the institutional phrasing to `METRIC_LABELS`.
 * 3. If the key has alternate spellings (e.g. "cvar_95", "cvar95",
 *    "expected_shortfall"), route them through `humanizeMetric`'s
 *    normalisation branch — never add alternate keys as top-level
 *    entries, that splinters the dictionary.
 */

export type QuantMetricKey =
	| "cvar_95"
	| "expected_shortfall"
	| "regime"
	| "garch_volatility"
	| "ewma_volatility"
	| "cfnai"
	| "macro_score"
	| "drawdown"
	| "max_drawdown";

const METRIC_LABELS: Readonly<Record<QuantMetricKey, string>> = {
	cvar_95: "Conditional Tail Risk (CVaR 95%)",
	expected_shortfall: "Conditional Tail Risk (CVaR 95%)",
	regime: "Market Regime",
	garch_volatility: "Conditional Volatility",
	ewma_volatility: "Conditional Volatility",
	cfnai: "Real Economy Activity Index",
	macro_score: "Real Economy Activity Index",
	drawdown: "Maximum Drawdown",
	max_drawdown: "Maximum Drawdown",
};

/**
 * Normalise an incoming metric key to the canonical QuantMetricKey.
 * Accepts snake_case, camelCase, SCREAMING, hyphenated, and a few
 * well-known aliases. Returns `null` for unknown keys so callers
 * can fall back to the raw string if they prefer.
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
		case "macro_score":
		case "macroscore":
			return "macro_score";
		case "drawdown":
		case "max_drawdown":
		case "maxdrawdown":
		case "maximum_drawdown":
			return "max_drawdown";
		default:
			return null;
	}
}

/**
 * Translate a raw quant metric key into its institutional label.
 * Unknown keys fall through to the input string so ad-hoc metrics
 * keep rendering — never silently hide a field from the user.
 */
export function humanizeMetric(raw: string): string {
	const key = normalise(raw);
	if (key && METRIC_LABELS[key]) return METRIC_LABELS[key];
	return raw;
}

/**
 * Regime label translation — Risk Methodology v3 tri-state phrasing.
 *
 * Backend emits uppercase enum (`RISK_ON` / `RISK_OFF` / `CRISIS`).
 * The institutional reading is Expansion (benign growth), Cautious
 * (late-cycle / mixed signals), and Stress (drawdown / crisis).
 * `NEUTRAL` is an intermediate state that maps to Cautious.
 *
 * Unknown labels pass through unchanged so a new backend regime
 * (e.g. `STAGFLATION`) is visible rather than silently relabelled.
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
 * Fully-qualified header string for the market regime tri-state —
 * used in chart titles and section headings.
 */
export const MARKET_REGIME_HEADER = "Market Regime: Expansion / Cautious / Stress";

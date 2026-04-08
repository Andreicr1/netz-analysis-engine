/**
 * Analytics grid spec — Phase 6 Block A IA pin.
 *
 * Maps each (scope, group) pair to the list of chart cells that the
 * AnalysisGrid renders. Block A returns placeholder names so Andrei
 * can review the IA + layout stability before Block B commits to
 * ECharts integration. Block B will swap each ``placeholder`` entry
 * for a real ``component: SvelteComponent`` reference.
 *
 * The 4 groups (per plan §5.4):
 *   - Returns & Risk → NavHero, Rolling Risk, Drawdown
 *   - Holdings       → Holdings Treemap, Return Distribution
 *   - Peer           → Monthly Returns Heatmap, Risk Metrics Bullet
 *   - Stress         → Stress Impact Matrix
 *
 * The 5 portfolio-specific charts from Block B (Brinson Waterfall,
 * Factor Exposure, Constituent Correlation, Risk Attribution, Holdings
 * Treemap) are slotted into the appropriate group cells per the plan
 * §6.3.
 */

import type {
	AnalyticsGroupFocus,
	AnalyticsScope,
} from "./analytics-types";

export interface PlaceholderSpec {
	/** Stable id used as the {#each} key. */
	id: string;
	/** Display name shown in the placeholder card. */
	chartName: string;
	/** Plain-English description of what the chart will show. */
	description: string;
	/** Grid column span (1 | 2 | 3) — defaults to 1. */
	span?: 1 | 2 | 3;
}

export interface GridSpec {
	/** ChartCard tiles to render for the active scope + group. */
	cells: PlaceholderSpec[];
	/** Headline shown above the grid. */
	heading: string;
	/** Optional subtitle / context message. */
	subtitle?: string;
}

const RETURNS_RISK_CELLS: PlaceholderSpec[] = [
	{
		id: "nav-hero",
		chartName: "NAV Hero",
		description:
			"Cumulative NAV curve with regime overlay markAreas and benchmark line.",
	},
	{
		id: "rolling-risk",
		chartName: "Rolling Risk",
		description:
			"Rolling 60d volatility, downside deviation, and max drawdown.",
	},
	{
		id: "drawdown-underwater",
		chartName: "Drawdown Underwater",
		description:
			"Underwater curve with peak/trough markers and recovery shading.",
	},
];

const HOLDINGS_CELLS: PlaceholderSpec[] = [
	{
		id: "holdings-treemap",
		chartName: "Holdings Treemap",
		description:
			"Treemap of effective weights, sized by NAV exposure and coloured by sector.",
		span: 2,
	},
	{
		id: "return-distribution",
		chartName: "Return Distribution",
		description:
			"Histogram of monthly returns with normal-fit overlay and skew/kurtosis chips.",
	},
];

const PEER_CELLS: PlaceholderSpec[] = [
	{
		id: "monthly-returns-heatmap",
		chartName: "Monthly Returns Heatmap",
		description:
			"Calendar heatmap of monthly returns with peer-relative diverging colour scale.",
		span: 2,
	},
	{
		id: "risk-metrics-bullet",
		chartName: "Risk Metrics Bullet",
		description:
			"Bullet chart of CVaR, Sharpe, Sortino, Calmar vs peer-group quartiles.",
	},
];

const STRESS_CELLS: PlaceholderSpec[] = [
	{
		id: "stress-impact-matrix",
		chartName: "Stress Impact Matrix",
		description:
			"NAV impact and CVaR impact across the 4 canonical DL7 stress scenarios.",
		span: 3,
	},
];

const HEADINGS: Record<AnalyticsGroupFocus, { heading: string; subtitle: string }> = {
	returns_risk: {
		heading: "Returns & Risk",
		subtitle:
			"Drawdowns, rolling volatility, and NAV evolution against the benchmark.",
	},
	holdings: {
		heading: "Holdings",
		subtitle:
			"Composition, concentration, and return distribution.",
	},
	peer: {
		heading: "Peer Comparison",
		subtitle:
			"Heatmaps and bullet charts vs the peer-group quartiles.",
	},
	stress: {
		heading: "Stress",
		subtitle:
			"How the subject behaves in the 4 canonical scenarios.",
	},
};

/**
 * Compute the AnalysisGrid spec for a (scope, group) pair. The same
 * spec is returned for both ``model_portfolios`` and
 * ``approved_universe`` scopes in Phase 6 Block A — Block B will
 * branch on scope where the chart data shape differs (e.g. peer
 * comparison only makes sense for instruments, not portfolios).
 *
 * Compare Both is locked to v1.1 — when the scope arrives here it
 * returns an empty cell array so the grid renders a v1.1 placeholder
 * instead of duplicating the cells.
 */
export function buildGridSpec(
	scope: AnalyticsScope,
	group: AnalyticsGroupFocus,
): GridSpec {
	if (scope === "compare_both") {
		return {
			heading: HEADINGS[group].heading,
			subtitle: "Compare Both ships in v1.1.",
			cells: [],
		};
	}

	let cells: PlaceholderSpec[];
	switch (group) {
		case "returns_risk":
			cells = RETURNS_RISK_CELLS;
			break;
		case "holdings":
			cells = HOLDINGS_CELLS;
			break;
		case "peer":
			cells = PEER_CELLS;
			break;
		case "stress":
			cells = STRESS_CELLS;
			break;
	}

	return {
		heading: HEADINGS[group].heading,
		subtitle: HEADINGS[group].subtitle,
		cells,
	};
}

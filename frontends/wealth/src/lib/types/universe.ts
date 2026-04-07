/** Universe domain types — maps 1:1 to backend schemas. */

export type InstrumentType = "fund" | "bond" | "equity";

export interface UniverseAsset {
	instrument_id: string;
	fund_name: string;
	ticker?: string | null;
	isin?: string | null;
	instrument_type?: InstrumentType | null;
	block_id: string | null;
	geography: string | null;
	investment_geography: string | null;
	asset_class: string | null;
	approval_status: string | null;
	approval_decision: string;
	approved_at: string | null;
	/** Tier 1 density fields — see Flexible Columns Layout spec §3.1. */
	aum_usd: number | null;
	expense_ratio: number | null;
	return_3y_ann: number | null;
	sharpe_1y: number | null;
	max_drawdown_1y: number | null;
	blended_momentum_score: number | null;
	liquidity_tier: string | null;
	manager_score: number | null;
	/**
	 * Pearson correlation of the candidate's daily return series
	 * against the equal-weight synthetic portfolio of the funds
	 * currently in the Builder workspace. Populated by `GET /universe`
	 * when the loader passes `?current_holdings=<uuid1>,<uuid2>,...`.
	 * `null` when the Builder is empty, when the candidate has
	 * insufficient NAV history overlap (< 45 days), or when the
	 * backend correlation service failed (best-effort enrichment).
	 *
	 * Frontend renders "—" for null, otherwise formatNumber(value, 2)
	 * with a red→green color scale (negative = diversifying, positive
	 * = concentrating).
	 *
	 * Spec: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §3.4
	 */
	correlation_to_portfolio: number | null;
}

export function instrumentTypeLabel(type: InstrumentType | string | null | undefined): string {
	switch (type) {
		case "fund":   return "Fund";
		case "bond":   return "Fixed Income";
		case "equity": return "Equity";
		default:       return type ?? "—";
	}
}

export function instrumentTypeColor(type: InstrumentType | string | null | undefined): string {
	switch (type) {
		case "fund":   return "var(--ii-brand-primary)";
		case "bond":   return "var(--ii-brand-highlight)";
		case "equity": return "var(--ii-success)";
		default:       return "var(--ii-text-muted)";
	}
}

export interface UniverseApproval {
	id: string;
	instrument_id: string;
	analysis_report_id: string | null;
	decision: "pending" | "approved" | "rejected" | "watchlist";
	rationale: string | null;
	created_by: string | null;
	decided_by: string | null;
	decided_at: string | null;
	is_current: boolean;
	created_at: string;
	fund_name: string | null;
	ticker: string | null;
	block_id: string | null;
}

/** Risk metrics — shared across all instrument types (fund, bond, equity). */
export interface InstrumentRiskMetrics {
	instrument_id: string;
	calc_date: string;
	cvar_95_1m: number | null;
	cvar_95_3m: number | null;
	cvar_95_6m: number | null;
	cvar_95_12m: number | null;
	var_95_1m: number | null;
	var_95_3m: number | null;
	var_95_6m: number | null;
	var_95_12m: number | null;
	return_1m: number | null;
	return_3m: number | null;
	return_6m: number | null;
	return_1y: number | null;
	return_3y_ann: number | null;
	volatility_1y: number | null;
	max_drawdown_1y: number | null;
	max_drawdown_3y: number | null;
	sharpe_1y: number | null;
	sharpe_3y: number | null;
	sortino_1y: number | null;
	alpha_1y: number | null;
	beta_1y: number | null;
	information_ratio_1y: number | null;
	tracking_error_1y: number | null;
	manager_score: number | null;
	score_components: Record<string, unknown> | null;
	rsi_14: number | null;
	bb_position: number | null;
	nav_momentum_score: number | null;
	flow_momentum_score: number | null;
	blended_momentum_score: number | null;
	dtw_drift_score: number | null;
}

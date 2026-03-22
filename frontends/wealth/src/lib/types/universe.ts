/** Universe domain types — maps 1:1 to backend schemas. */

export type InstrumentType = "fund" | "bond" | "equity";

export interface UniverseAsset {
	fund_id: string;
	fund_name: string;
	instrument_type: InstrumentType | null;
	block_id: string | null;
	geography: string | null;
	asset_class: string | null;
	approval_status: string | null;
	approval_decision: "approved" | "watchlist";
	approved_at: string | null;
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
		case "fund":   return "var(--netz-brand-primary)";
		case "bond":   return "var(--netz-brand-highlight)";
		case "equity": return "var(--netz-success)";
		default:       return "var(--netz-text-muted)";
	}
}

export interface UniverseApproval {
	id: string;
	instrument_id: string;
	analysis_report_id: string;
	decision: "pending" | "approved" | "rejected" | "watchlist";
	rationale: string | null;
	created_by: string | null;
	decided_by: string | null;
	decided_at: string | null;
	is_current: boolean;
	created_at: string;
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

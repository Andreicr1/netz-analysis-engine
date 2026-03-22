/** Model Portfolio domain types — maps 1:1 to backend schemas. */

export interface ModelPortfolio {
	id: string;
	profile: string;
	display_name: string;
	description: string | null;
	benchmark_composite: string | null;
	inception_date: string | null;
	backtest_start_date: string | null;
	inception_nav: number;
	status: string;
	fund_selection_schema: SelectionSchema | null;
	created_at: string;
	created_by: string | null;
}

export interface SelectionSchema {
	profile: string;
	total_weight: number;
	funds: InstrumentWeight[];
}

export interface InstrumentWeight {
	instrument_id: string;
	fund_name: string;
	instrument_type: "fund" | "bond" | "equity" | null;
	block_id: string;
	weight: number;
	score: number;
}

/** @deprecated Use SelectionSchema */
export type FundSelectionSchema = SelectionSchema;
/** @deprecated Use InstrumentWeight */
export type FundWeight = InstrumentWeight;

export interface BacktestFold {
	fold: number;
	sharpe: number | null;
	cvar_95: number | null;
	max_drawdown: number | null;
	n_obs: number;
}

export interface BacktestResult {
	mean_sharpe: number | null;
	std_sharpe: number | null;
	positive_folds: number;
	total_folds: number;
	youngest_fund_start: string | null;
	folds: BacktestFold[];
}

export interface StressScenario {
	name: string;
	start_date: string;
	end_date: string;
	portfolio_return: number;
	max_drawdown: number;
	recovery_days: number | null;
}

export interface StressResult {
	scenarios: StressScenario[];
}

export interface TrackRecord {
	portfolio_id: string;
	profile: string;
	status: string;
	fund_selection: SelectionSchema | null;
	backtest: BacktestResult | null;
	live_nav: unknown;
	stress: StressResult | null;
}

export function scenarioLabel(name: string): string {
	switch (name) {
		case "2008_gfc": return "2008 GFC";
		case "2020_covid": return "2020 COVID";
		case "2022_rate_hike": return "2022 Rate Hike";
		default: return name.replace(/_/g, " ");
	}
}

export function profileColor(profile: string): string {
	switch (profile) {
		case "conservative": return "var(--netz-info)";
		case "moderate": return "var(--netz-warning)";
		case "growth": return "var(--netz-success)";
		default: return "var(--netz-text-secondary)";
	}
}

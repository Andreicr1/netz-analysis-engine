/** Screening domain types — maps 1:1 to backend schemas. */

export interface CriterionResult {
	criterion: string;
	expected: string;
	actual: string;
	passed: boolean;
	layer: number;
}

export interface ScreeningResult {
	id: string;
	instrument_id: string;
	run_id: string;
	overall_status: "PASS" | "FAIL" | "WATCHLIST";
	score: number | null;
	failed_at_layer: number | null;
	layer_results: CriterionResult[];
	required_analysis_type: "dd_report" | "bond_brief" | "none";
	screened_at: string;
	is_current: boolean;
	/** Joined from instruments_universe */
	name?: string;
	isin?: string;
	ticker?: string;
	instrument_type?: string;
	block_id?: string | null;
	manager?: string;
	manager_crd?: string | null;
	geography?: string;
	strategy?: string;
	aum?: number | null;
	currency?: string;
}

export interface ScreeningRun {
	run_id: string;
	instrument_count: number;
	started_at: string;
	completed_at: string | null;
	status: "running" | "completed";
}

export type OverallStatus = "PASS" | "FAIL" | "WATCHLIST";

export interface ScreenerFilterConfig {
	status: OverallStatus | null;
	instrument_type: string | null;
	block_id: string | null;
	search: string;
}

export const EMPTY_FILTERS: ScreenerFilterConfig = {
	status: null,
	instrument_type: null,
	block_id: null,
	search: "",
};

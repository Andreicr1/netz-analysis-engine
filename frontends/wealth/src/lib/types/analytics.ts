/** Analytics domain types — Attribution, Drift, Correlation. */

export interface SectorAttribution {
	sector: string;
	block_id: string;
	allocation_effect: number;
	selection_effect: number;
	interaction_effect: number;
	total_effect: number;
}

export interface AttributionResult {
	profile: string;
	start_date: string;
	end_date: string;
	granularity: "monthly" | "quarterly";
	total_portfolio_return: number;
	total_benchmark_return: number;
	total_excess_return: number;
	allocation_total: number;
	selection_total: number;
	interaction_total: number;
	total_allocation_combined: number;
	sectors: SectorAttribution[];
	n_periods: number;
	benchmark_available: boolean;
	benchmark_approach: string;
}

export interface MetricDrift {
	metric_name: string;
	recent_mean: number;
	baseline_mean: number;
	baseline_std: number;
	z_score: number;
	is_anomalous: boolean;
}

export interface StrategyDriftAlert {
	alert_type: string;
	instrument_id: string;
	instrument_name: string;
	status: string;
	anomalous_count: number;
	total_metrics: number;
	metrics: MetricDrift[];
	severity: "none" | "moderate" | "severe";
	detected_at: string;
}

export interface ParetoResult {
	profile: string;
	recommended_weights: Record<string, number>;
	pareto_sharpe: number[];
	pareto_cvar: number[];
	n_solutions: number;
	seed: number;
	input_hash: string;
	status: string;
	job_id?: string;
}

export type Timeframe = "ytd" | "1y" | "3y" | "custom";

export function effectColor(value: number): string {
	if (value > 0.001) return "var(--netz-success)";
	if (value < -0.001) return "var(--netz-danger)";
	return "var(--netz-text-muted)";
}

export function severityColor(severity: string): string {
	switch (severity) {
		case "severe":   return "var(--netz-danger)";
		case "moderate": return "var(--netz-warning)";
		default:         return "var(--netz-success)";
	}
}

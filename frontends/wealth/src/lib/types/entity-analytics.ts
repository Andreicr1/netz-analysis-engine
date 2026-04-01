/** Entity Analytics types — mirrors backend EntityAnalyticsResponse schema. */

export interface RiskStatistics {
	annualized_return: number | null;
	annualized_volatility: number | null;
	sharpe_ratio: number | null;
	sortino_ratio: number | null;
	calmar_ratio: number | null;
	max_drawdown: number | null;
	alpha: number | null;
	beta: number | null;
	tracking_error: number | null;
	information_ratio: number | null;
	n_observations: number;
}

export interface DrawdownPeriod {
	start_date: string;
	trough_date: string;
	end_date: string | null;
	depth: number;
	duration_days: number;
	recovery_days: number | null;
}

export interface DrawdownAnalysis {
	dates: string[];
	values: number[];
	max_drawdown: number | null;
	current_drawdown: number | null;
	longest_duration_days: number | null;
	avg_recovery_days: number | null;
	worst_periods: DrawdownPeriod[];
}

export interface CaptureRatios {
	up_capture: number | null;
	down_capture: number | null;
	up_number_ratio: number | null;
	down_number_ratio: number | null;
	up_periods: number;
	down_periods: number;
	benchmark_source: string;
	benchmark_label: string;
}

export interface RollingSeries {
	window_label: string;
	dates: string[];
	values: number[];
}

export interface RollingReturns {
	series: RollingSeries[];
}

export interface ReturnDistribution {
	bin_edges: number[];
	bin_counts: number[];
	mean: number | null;
	std: number | null;
	skewness: number | null;
	kurtosis: number | null;
	var_95: number | null;
	cvar_95: number | null;
}

/** eVestment Sections I-V return statistics. */
export interface ReturnStatistics {
	arithmetic_mean_monthly: number | null;
	geometric_mean_monthly: number | null;
	avg_monthly_gain: number | null;
	avg_monthly_loss: number | null;
	gain_loss_ratio: number | null;
	gain_std_dev: number | null;
	loss_std_dev: number | null;
	downside_deviation: number | null;
	semi_deviation: number | null;
	sterling_ratio: number | null;
	omega_ratio: number | null;
	treynor_ratio: number | null;
	jensen_alpha: number | null;
	up_percentage_ratio: number | null;
	down_percentage_ratio: number | null;
	r_squared: number | null;
}

/** eVestment Section VII tail risk measures. */
export interface TailRiskMetrics {
	var_parametric_90: number | null;
	var_parametric_95: number | null;
	var_parametric_99: number | null;
	var_modified_95: number | null;
	var_modified_99: number | null;
	etl_95: number | null;
	etl_modified_95: number | null;
	etr_95: number | null;
	starr_ratio: number | null;
	rachev_ratio: number | null;
	jarque_bera_stat: number | null;
	jarque_bera_pvalue: number | null;
	is_normal: boolean | null;
}

export interface EntityAnalyticsResponse {
	entity_id: string;
	entity_type: "instrument" | "model_portfolio";
	entity_name: string;
	as_of_date: string;
	window: string;
	risk_statistics: RiskStatistics;
	drawdown: DrawdownAnalysis;
	capture: CaptureRatios;
	rolling_returns: RollingReturns;
	distribution: ReturnDistribution;
	return_statistics: ReturnStatistics | null;
	tail_risk: TailRiskMetrics | null;
}

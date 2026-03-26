/** Entity Analytics Vitrine — polymorphic analytics for funds and model portfolios. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { redirect } from "@sveltejs/kit";

export interface EntityAnalyticsData {
	entity_id: string;
	entity_type: "instrument" | "model_portfolio";
	entity_name: string;
	as_of_date: string;
	window: string;
	risk_statistics: {
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
	};
	drawdown: {
		dates: string[];
		values: number[];
		max_drawdown: number | null;
		current_drawdown: number | null;
		longest_duration_days: number | null;
		avg_recovery_days: number | null;
		worst_periods: Array<{
			start_date: string;
			trough_date: string;
			end_date: string | null;
			depth: number;
			duration_days: number;
			recovery_days: number | null;
		}>;
	};
	capture: {
		up_capture: number | null;
		down_capture: number | null;
		up_number_ratio: number | null;
		down_number_ratio: number | null;
		up_periods: number;
		down_periods: number;
		benchmark_source: "param" | "block" | "spy_fallback";
		benchmark_label: string;
	};
	rolling_returns: {
		series: Array<{
			window_label: string;
			dates: string[];
			values: number[];
		}>;
	};
	distribution: {
		bin_edges: number[];
		bin_counts: number[];
		mean: number | null;
		std: number | null;
		skewness: number | null;
		kurtosis: number | null;
		var_95: number | null;
		cvar_95: number | null;
	};
}

export const load: PageServerLoad = async ({ parent, url }) => {
	const entityId = url.searchParams.get("entity_id");
	if (!entityId) {
		redirect(302, "/screener");
	}

	const window = url.searchParams.get("window") ?? "1y";
	const benchmarkId = url.searchParams.get("benchmark_id");

	const { token } = await parent();
	const api = createServerApiClient(token);

	const params: Record<string, string> = { window };
	if (benchmarkId) params.benchmark_id = benchmarkId;

	const analytics = await api
		.get<EntityAnalyticsData>(`/analytics/entity/${entityId}`, params)
		.catch(() => null);

	return { analytics, entityId, window };
};

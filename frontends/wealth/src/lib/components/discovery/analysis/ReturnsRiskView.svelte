<!--
  ReturnsRiskView — composition of 6 ChartCards inside an AnalysisGrid for
  the "Returns & Risk" group of the Analysis page.

  Fetches `/funds/{id}/analysis/returns-risk?window=...` via analysis-api
  using an AbortController-scoped $effect. Handles loading, error, and
  institutional empty state (private funds with `disclosure.has_nav === false`).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import {
		fetchReturnsRisk,
		type AnalysisWindow,
		type RiskMetricsPayload,
	} from "$lib/discovery/analysis-api";
	import { AnalysisGrid, ChartCard } from "@investintell/ui";
	import NavHeroChart from "$lib/components/charts/discovery/NavHeroChart.svelte";
	import RollingRiskChart from "$lib/components/charts/discovery/RollingRiskChart.svelte";
	import MonthlyReturnsHeatmap from "$lib/components/charts/discovery/MonthlyReturnsHeatmap.svelte";
	import ReturnDistributionChart from "$lib/components/charts/discovery/ReturnDistributionChart.svelte";
	import DrawdownUnderwaterChart from "$lib/components/charts/discovery/DrawdownUnderwaterChart.svelte";
	import RiskMetricsBulletChart from "$lib/components/charts/discovery/RiskMetricsBulletChart.svelte";

	interface NavPoint {
		nav_date: string;
		nav: number;
		return_1d: number | null;
	}
	interface MonthlyPoint {
		month: string;
		compound_return: number;
		compound_log_return: number;
		trading_days: number;
		min_nav: number;
		max_nav: number;
	}
	interface RollingPoint {
		date: string;
		rolling_vol: number | null;
		rolling_sharpe: number | null;
	}
	interface Distribution {
		bins: number[];
		counts: number[];
		mean: number | null;
	}
	interface ReturnsRiskPayload {
		window: string;
		nav_series: NavPoint[];
		monthly_returns: MonthlyPoint[];
		rolling_metrics: RollingPoint[];
		return_distribution: Distribution;
		risk_metrics: RiskMetricsPayload | null;
		disclosure: { has_nav: boolean };
		fund: Record<string, unknown>;
	}

	interface Props {
		fundId: string;
		window: AnalysisWindow;
	}

	let { fundId, window }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let data = $state<ReturnsRiskPayload | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		const id = fundId;
		const w = window;
		if (!id || !getToken) return;
		const ctrl = new AbortController();
		data = null;
		error = null;
		fetchReturnsRisk(getToken, id, w, ctrl.signal)
			.then((d) => {
				data = d as ReturnsRiskPayload;
			})
			.catch((e: unknown) => {
				if (e instanceof Error && e.name !== "AbortError") {
					error = e.message;
				}
			});
		return () => ctrl.abort();
	});

	const hasNav = $derived(
		!!data && data.disclosure?.has_nav && data.nav_series.length > 0,
	);
</script>

{#if error}
	<div class="rv-error">Failed to load: {error}</div>
{:else if !data}
	<div class="rv-loading">Loading Returns &amp; Risk…</div>
{:else if !hasNav}
	<div class="rv-empty">
		<strong>No public pricing data</strong>
		<p>
			This fund reports via Form ADV filings only. Public NAV series is
			not available, so Returns &amp; Risk analysis cannot be computed.
			Use the Holdings or Peer tabs instead.
		</p>
	</div>
{:else}
	<AnalysisGrid>
		<ChartCard
			title="Cumulative Return & Drawdown"
			span={3}
			minHeight="420px"
		>
			<NavHeroChart series={data.nav_series} />
		</ChartCard>
		<ChartCard title="Rolling Risk (12 months)">
			<RollingRiskChart rolling={data.rolling_metrics} />
		</ChartCard>
		<ChartCard title="Monthly Returns Heatmap">
			<MonthlyReturnsHeatmap monthly={data.monthly_returns} />
		</ChartCard>
		<ChartCard title="Return Distribution">
			<ReturnDistributionChart distribution={data.return_distribution} />
		</ChartCard>
		<ChartCard title="Drawdown (Underwater)">
			<DrawdownUnderwaterChart series={data.nav_series} />
		</ChartCard>
		<ChartCard title="How this fund compares on risk" span={2}>
			<RiskMetricsBulletChart metrics={data.risk_metrics} />
		</ChartCard>
	</AnalysisGrid>
{/if}

<style>
	.rv-error,
	.rv-loading,
	.rv-empty {
		padding: 40px;
		text-align: center;
		color: var(--ii-text-muted);
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.rv-empty strong {
		display: block;
		font-size: 14px;
		color: var(--ii-text-primary);
		margin-bottom: 8px;
	}
	.rv-empty p {
		max-width: 480px;
		margin: 0 auto;
		font-size: 12px;
		line-height: 1.6;
	}
</style>

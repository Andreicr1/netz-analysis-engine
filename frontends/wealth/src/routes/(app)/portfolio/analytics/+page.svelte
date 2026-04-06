<!--
  Analytics & Risk — Portfolio-level analytics with sub-pill navigation.
  Sub-pills: Attribution | Factor Analysis | Strategy Drift | Risk Budget
  Each section renders full-width below the sub-pills.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { EmptyState, formatPercent, formatNumber, formatBps } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { workspace, type FactorContribution } from "$lib/state/portfolio-workspace.svelte";
	import { effectColor, severityColor } from "$lib/types/analytics";
	import type { AttributionResult, StrategyDriftAlert, CorrelationRegimeResult } from "$lib/types/analytics";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	// Seed workspace with SSR analytics data
	$effect(() => {
		const ssrAttribution = data.attribution as AttributionResult | null;
		const ssrDrift = (data.driftAlerts ?? []) as StrategyDriftAlert[];
		const ssrCorrelation = data.correlationRegime as CorrelationRegimeResult | null;
		if (ssrAttribution && !workspace.attribution) workspace.attribution = ssrAttribution;
		if (ssrDrift.length > 0 && workspace.driftAlerts.length === 0) workspace.driftAlerts = ssrDrift;
		if (ssrCorrelation && !workspace.correlationRegime) workspace.correlationRegime = ssrCorrelation;
	});

	// ── Derived state ───────────────────────────────────────────────
	let attribution = $derived(workspace.attribution);
	let driftAlerts = $derived(workspace.driftAlerts);
	let factorData = $derived(workspace.localFactorAnalysis);
	let riskBudget = $derived(workspace.riskBudget);

	let hasPortfolio = $derived(workspace.portfolio != null);

	const subTabs = [
		{ value: "attribution", label: "Attribution" },
		{ value: "factor", label: "Factor Analysis" },
		{ value: "drift", label: "Strategy Drift" },
		{ value: "risk-budget", label: "Risk Budget" },
	] as const;

	// ── Attribution Chart ────────────────────────────────────────────
	let sectors = $derived(attribution?.sectors ?? []);

	let attributionChartOption = $derived.by(() => {
		if (sectors.length === 0) return null;
		const names = sectors.map((s) => s.sector);
		const allocData = sectors.map((s) => +(s.allocation_effect * 10000).toFixed(1));
		const selData = sectors.map((s) => +(s.selection_effect * 10000).toFixed(1));
		return {
			...globalChartOptions,
			toolbox: { show: false },
			tooltip: {
				trigger: "axis" as const,
				axisPointer: { type: "shadow" as const },
				valueFormatter: (v: number) => `${v >= 0 ? "+" : ""}${formatNumber(v, 1, "en-US")} bps`,
			},
			legend: { data: ["Allocation", "Selection"], bottom: 0, textStyle: { color: "#85a0bd", fontSize: 11 } },
			grid: { containLabel: true, left: 16, right: 24, top: 12, bottom: 36 },
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: (v: number) => `${v} bps`, fontSize: 10, color: "#85a0bd" },
				splitLine: { lineStyle: { color: "rgba(64,66,73,0.3)", type: "dashed" as const } },
			},
			yAxis: {
				type: "category" as const, data: names,
				axisLabel: { width: 140, overflow: "truncate" as const, fontSize: 12, color: "#cbccd1" },
			},
			series: [
				{ name: "Allocation", type: "bar" as const, data: allocData, itemStyle: { color: "#11ec79", borderRadius: [0, 3, 3, 0] } },
				{ name: "Selection", type: "bar" as const, data: selData, itemStyle: { color: "#0194ff", borderRadius: [0, 3, 3, 0] } },
			],
		} as Record<string, unknown>;
	});

	// ── Factor Donut ────────────────────────────────────────────────
	let donutOption = $derived.by(() => {
		if (!factorData) return {};
		const contribs = factorData.factor_contributions || [];
		const slices = contribs.length > 0
			? contribs.map((fc: FactorContribution) => ({ value: fc.pct_contribution * 100, name: fc.factor_label }))
			: [
				{ value: factorData.systematic_risk_pct * 100, name: "Systematic" },
				{ value: factorData.specific_risk_pct * 100, name: "Idiosyncratic" },
			];
		const colors = [
			[{offset: 0, color: '#0194ff'}, {offset: 1, color: '#0054c2'}],
			[{offset: 0, color: '#1ceba7'}, {offset: 1, color: '#0a8844'}],
			[{offset: 0, color: '#ebb94d'}, {offset: 1, color: '#9d6d13'}],
			[{offset: 0, color: '#c418e6'}, {offset: 1, color: '#7a0a91'}],
			[{offset: 0, color: '#ff4d4d'}, {offset: 1, color: '#cc0000'}],
		];
		return {
			...globalChartOptions, toolbox: { show: false },
			tooltip: { ...globalChartOptions.tooltip, trigger: "item" as const },
			legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: '#85a0bd' } },
			series: [{
				type: "pie" as const, radius: ["48%", "72%"], center: ["50%", "44%"],
				label: { show: false }, labelLine: { show: false },
				itemStyle: { borderColor: '#1a1b20', borderWidth: 3, borderRadius: 4 },
				emphasis: { label: { show: true, fontSize: 13, fontWeight: 700, color: '#fff' } },
				data: slices.map((s: { value: number; name: string }, i: number) => ({
					...s,
					itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: colors[i % colors.length] } },
				})),
			}],
		};
	});

	// ── Factor Exposures Bar ────────────────────────────────────────
	let barOption = $derived.by(() => {
		if (!factorData) return {};
		const exposures = factorData.portfolio_factor_exposures || {};
		const categories = Object.keys(exposures);
		const values = Object.values(exposures).map((v: unknown) => Math.round((v as number) * 1000) / 1000);
		return {
			...globalChartOptions, toolbox: { show: false },
			grid: { left: 120, right: 50, top: 8, bottom: 24, containLabel: false },
			tooltip: { ...globalChartOptions.tooltip, trigger: "axis" as const, axisPointer: { type: 'shadow' } },
			xAxis: {
				type: "value" as const, min: -1, max: 1,
				axisLabel: { formatter: "{value}", fontSize: 10, color: '#85a0bd' },
				splitLine: { lineStyle: { type: "dashed" as const, color: 'rgba(64,66,73,0.3)' } },
			},
			yAxis: {
				type: "category" as const, data: categories, inverse: true,
				axisLabel: { fontSize: 12, fontWeight: 600, color: '#cbccd1' },
				axisTick: { show: false }, axisLine: { show: false },
			},
			series: [{
				type: "bar" as const, barWidth: "45%",
				data: values.map((v) => ({
					value: v,
					itemStyle: {
						color: v >= 0
							? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#09a552'}, {offset: 1, color: '#11ec79'}] }
							: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#fc1a1a'}, {offset: 1, color: '#a30c0c'}] },
						borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
					},
				})),
				label: {
					show: true, position: "right" as const, fontSize: 11, fontWeight: 600, color: '#fff',
					formatter: (p: { value: number }) => `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}`,
				},
				markLine: {
					silent: true, symbol: "none" as const,
					data: [{ xAxis: 0 }],
					lineStyle: { color: "#71717a", type: "solid" as const, width: 1 },
					label: { show: false },
				},
			}],
		};
	});

	function fmtBps(v: number): string {
		return formatBps(v, { decimals: 1, signed: true });
	}
</script>

<svelte:head>
	<title>Analytics & Risk — InvestIntell</title>
</svelte:head>

<div class="an-page">

	<!-- ── Sub-pill bar ── -->
	<div class="an-sub-pills">
		{#each subTabs as tab (tab.value)}
			{@const active = workspace.activeAnalyticsTab === tab.value}
			<button
				type="button"
				class="an-sub-pill"
				class:an-sub-pill--active={active}
				onclick={() => workspace.activeAnalyticsTab = tab.value}
			>
				{tab.label}
			</button>
		{/each}
	</div>

	<!-- ── Content ── -->
	<div class="an-content">

		<!-- ═══ Attribution ═══ -->
		{#if workspace.activeAnalyticsTab === "attribution"}
			{#if workspace.isLoadingAttribution}
				<div class="an-loading">
					<Loader2 class="h-6 w-6 animate-spin text-[#0177fb]" />
					<span>Loading attribution...</span>
				</div>
			{:else if attribution}
				<!-- KPI row -->
				<div class="an-kpi-row">
					<div class="an-kpi">
						<span class="an-kpi-label">Portfolio</span>
						<span class="an-kpi-value">{formatPercent(attribution.total_portfolio_return)}</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Benchmark</span>
						<span class="an-kpi-value">{formatPercent(attribution.total_benchmark_return)}</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Excess</span>
						<span class="an-kpi-value" style:color={effectColor(attribution.total_excess_return)}>
							{fmtBps(attribution.total_excess_return)}
						</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Allocation</span>
						<span class="an-kpi-value" style:color={effectColor(attribution.allocation_total)}>
							{fmtBps(attribution.allocation_total)}
						</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Selection</span>
						<span class="an-kpi-value" style:color={effectColor(attribution.selection_total)}>
							{fmtBps(attribution.selection_total)}
						</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Periods</span>
						<span class="an-kpi-value">{attribution.n_periods}</span>
					</div>
				</div>

				<!-- Attribution chart (full-width) -->
				{#if attributionChartOption}
					<div class="an-chart-card">
						<div class="an-chart-title">Brinson-Fachler Attribution by Sector</div>
						<ChartContainer
							option={attributionChartOption}
							height={Math.max(260, sectors.length * 40 + 60)}
							ariaLabel="Attribution by sector"
						/>
					</div>
				{:else}
					<div class="an-hint">Attribution requires at least 2 periods of performance data.</div>
				{/if}
			{:else}
				<EmptyState
					title="No attribution data"
					message="Select a portfolio in the Builder to view Brinson-Fachler attribution analysis."
				/>
			{/if}

		<!-- ═══ Factor Analysis ═══ -->
		{:else if workspace.activeAnalyticsTab === "factor"}
			{#if workspace.isLoadingFactorAnalysis}
				<div class="an-loading">
					<Loader2 class="h-6 w-6 animate-spin text-[#a855f7]" />
					<span>Running factor analysis...</span>
				</div>
			{:else if factorData}
				<!-- Factor KPIs -->
				<div class="an-kpi-row">
					<div class="an-kpi">
						<span class="an-kpi-label">Systematic Risk</span>
						<span class="an-kpi-value">{formatPercent(factorData.systematic_risk_pct / 100, 1, "en-US")}</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Specific Risk</span>
						<span class="an-kpi-value">{formatPercent(factorData.specific_risk_pct / 100, 1, "en-US")}</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">R²</span>
						<span class="an-kpi-value">{formatNumber(factorData.r_squared, 4, "en-US")}</span>
					</div>
				</div>

				<!-- Side-by-side: Donut + Bar -->
				<div class="an-factor-grid">
					<div class="an-chart-card">
						<div class="an-chart-title">Risk Decomposition</div>
						<ChartContainer option={donutOption} height={320} ariaLabel="Risk decomposition donut" />
					</div>
					<div class="an-chart-card">
						<div class="an-chart-title">Style Factor Exposures</div>
						<ChartContainer option={barOption} height={320} ariaLabel="Style factor exposures" />
					</div>
				</div>
			{:else}
				<EmptyState
					title="No factor data"
					message="Select and construct a portfolio to run PCA factor analysis."
				/>
			{/if}

		<!-- ═══ Strategy Drift ═══ -->
		{:else if workspace.activeAnalyticsTab === "drift"}
			{#if workspace.isLoadingDrift}
				<div class="an-loading">
					<Loader2 class="h-6 w-6 animate-spin text-[#f59e0b]" />
					<span>Loading drift alerts...</span>
				</div>
			{:else if driftAlerts.length > 0}
				<div class="an-drift-header">
					<span class="an-drift-title">{driftAlerts.length} Drift Alert{driftAlerts.length !== 1 ? "s" : ""}</span>
				</div>
				<div class="an-drift-table">
					<div class="an-drift-thead">
						<span>Instrument</span>
						<span>Severity</span>
						<span>Anomalous</span>
						<span>Detected</span>
					</div>
					{#each driftAlerts as alert (alert.instrument_id)}
						<div class="an-drift-row">
							<span class="an-drift-name">{alert.instrument_name}</span>
							<span class="an-drift-severity" style:color={severityColor(alert.severity)}>
								{alert.severity}
							</span>
							<span class="an-drift-meta">{alert.anomalous_count}/{alert.total_metrics} metrics</span>
							<span class="an-drift-date">{alert.detected_at?.slice(0, 10) ?? "—"}</span>
						</div>
					{/each}
				</div>
			{:else}
				<EmptyState
					title="No drift alerts"
					message="All instruments are behaving within their historical baselines."
				/>
			{/if}

		<!-- ═══ Risk Budget ═══ -->
		{:else if workspace.activeAnalyticsTab === "risk-budget"}
			{#if !hasPortfolio}
				<EmptyState
					title="No portfolio selected"
					message="Select a portfolio in the Builder to compute risk budget decomposition."
				/>
			{:else if workspace.isLoadingRiskBudget}
				<div class="an-loading">
					<Loader2 class="h-6 w-6 animate-spin text-[#22c55e]" />
					<span>Computing risk budget...</span>
				</div>
			{:else if riskBudget}
				<div class="an-kpi-row">
					<div class="an-kpi">
						<span class="an-kpi-label">Portfolio Volatility</span>
						<span class="an-kpi-value">{formatPercent(riskBudget.portfolio_volatility)}</span>
					</div>
					<div class="an-kpi">
						<span class="an-kpi-label">Portfolio ETL</span>
						<span class="an-kpi-value">{formatPercent(riskBudget.portfolio_etl)}</span>
					</div>
					{#if riskBudget.portfolio_starr != null}
						<div class="an-kpi">
							<span class="an-kpi-label">STARR Ratio</span>
							<span class="an-kpi-value">{formatNumber(riskBudget.portfolio_starr, 3, "en-US")}</span>
						</div>
					{/if}
				</div>

				<!-- Risk budget table (full-width) -->
				<div class="an-rb-card">
					<div class="an-rb-thead">
						<span>Block</span>
						<span class="an-rb-right">Weight</span>
						<span class="an-rb-right">MCTR</span>
						<span class="an-rb-right">PCTR</span>
						<span class="an-rb-right">MCETL</span>
						<span class="an-rb-right">PCETL</span>
					</div>
					{#each riskBudget.funds as fund (fund.block_id)}
						<div class="an-rb-row">
							<span class="an-rb-name">{fund.block_name}</span>
							<span class="an-rb-val">{formatPercent(fund.weight)}</span>
							<span class="an-rb-val">{fund.mctr != null ? formatPercent(fund.mctr) : "—"}</span>
							<span class="an-rb-val">{fund.pctr != null ? formatPercent(fund.pctr) : "—"}</span>
							<span class="an-rb-val">{fund.mcetl != null ? formatPercent(fund.mcetl) : "—"}</span>
							<span class="an-rb-val">{fund.pcetl != null ? formatPercent(fund.pcetl) : "—"}</span>
						</div>
					{/each}
				</div>
			{:else}
				<div class="an-compute-cta">
					<p class="an-hint">Risk budget decomposition shows marginal/percentage contribution to risk per allocation block.</p>
					<Button
						variant="outline"
						disabled={workspace.isLoadingRiskBudget}
						onclick={() => workspace.loadRiskBudget()}
						class="h-10 text-[14px]"
					>
						Compute Risk Budget
					</Button>
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.an-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: 24px;
		overflow: hidden;
	}

	/* ── Sub-pills ── */
	.an-sub-pills {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.an-sub-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 8px 20px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 14px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
		letter-spacing: 0.02em;
	}

	.an-sub-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.an-sub-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.an-sub-pill--active:hover {
		background: #0166d9;
	}

	/* ── Content ── */
	.an-content {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 24px;
	}

	/* ── KPI row ── */
	.an-kpi-row {
		display: flex;
		gap: 1px;
		background: rgba(64, 66, 73, 0.3);
		border-radius: 16px;
		overflow: hidden;
	}

	.an-kpi {
		display: flex;
		flex-direction: column;
		gap: 3px;
		padding: 14px 18px;
		flex: 1;
		background: #141519;
	}

	.an-kpi-label {
		font-size: 12px;
		color: #85a0bd;
		font-weight: 500;
		font-family: "Urbanist", sans-serif;
	}

	.an-kpi-value {
		font-size: 16px;
		font-weight: 700;
		color: #fff;
		font-variant-numeric: tabular-nums;
		font-family: "Urbanist", sans-serif;
	}

	/* ── Chart card ── */
	.an-chart-card {
		background: #141519;
		border: 1px solid rgba(64, 66, 73, 0.3);
		border-radius: 20px;
		padding: 20px;
		overflow: hidden;
	}

	.an-chart-title {
		font-size: 13px;
		font-weight: 600;
		color: #85a0bd;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: 12px;
		font-family: "Urbanist", sans-serif;
	}

	/* ── Factor grid (2 columns) ── */
	.an-factor-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}

	/* ── Drift ── */
	.an-drift-header {
		padding: 0 0 4px;
	}

	.an-drift-title {
		font-size: 15px;
		font-weight: 700;
		color: #fff;
		font-family: "Urbanist", sans-serif;
	}

	.an-drift-table {
		background: #141519;
		border: 1px solid rgba(64, 66, 73, 0.3);
		border-radius: 16px;
		overflow: hidden;
	}

	.an-drift-thead {
		display: grid;
		grid-template-columns: 1fr 100px 120px 120px;
		gap: 8px;
		padding: 10px 20px;
		font-size: 11px;
		font-weight: 600;
		color: #71717a;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
		font-family: "Urbanist", sans-serif;
	}

	.an-drift-row {
		display: grid;
		grid-template-columns: 1fr 100px 120px 120px;
		gap: 8px;
		padding: 10px 20px;
		font-size: 14px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.15);
		align-items: center;
		font-family: "Urbanist", sans-serif;
	}

	.an-drift-row:last-child {
		border-bottom: none;
	}

	.an-drift-name {
		color: #cbccd1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-drift-severity {
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.02em;
	}

	.an-drift-meta {
		font-size: 13px;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
	}

	.an-drift-date {
		font-size: 13px;
		color: #71717a;
		font-variant-numeric: tabular-nums;
	}

	/* ── Risk budget table ── */
	.an-rb-card {
		background: #141519;
		border: 1px solid rgba(64, 66, 73, 0.3);
		border-radius: 16px;
		overflow: hidden;
	}

	.an-rb-thead {
		display: grid;
		grid-template-columns: 1fr 80px 80px 80px 80px 80px;
		gap: 8px;
		padding: 10px 20px;
		font-size: 11px;
		font-weight: 600;
		color: #71717a;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
		font-family: "Urbanist", sans-serif;
	}

	.an-rb-row {
		display: grid;
		grid-template-columns: 1fr 80px 80px 80px 80px 80px;
		gap: 8px;
		padding: 10px 20px;
		font-size: 14px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.15);
		font-family: "Urbanist", sans-serif;
	}

	.an-rb-row:last-child { border-bottom: none; }

	.an-rb-right { text-align: right; }

	.an-rb-name {
		color: #cbccd1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-rb-val {
		color: #fff;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	/* ── Shared ── */
	.an-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 64px 24px;
		color: #85a0bd;
		font-size: 14px;
		font-weight: 500;
		font-family: "Urbanist", sans-serif;
	}

	.an-hint {
		text-align: center;
		color: #71717a;
		font-size: 14px;
		font-family: "Urbanist", sans-serif;
	}

	.an-compute-cta {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 16px;
		padding: 64px 24px;
	}
</style>

<!--
  AnalyticsRiskPanel — Unified portfolio analytics & risk view.
  Sections: Attribution KPIs, Factor Decomposition, Strategy Drift, Risk Budget.
  Design: dark premium (Figma One X), matches portfolio workspace cards.
-->
<script lang="ts">
	import { formatPercent, formatNumber, formatBps } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { EmptyState } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import TrendingUp from "lucide-svelte/icons/trending-up";
	import ShieldAlert from "lucide-svelte/icons/shield-alert";
	import PieChart from "lucide-svelte/icons/pie-chart";
	import Scale from "lucide-svelte/icons/scale";
	import { workspace, type FactorContribution } from "$lib/state/portfolio-workspace.svelte";
	import { effectColor, severityColor } from "$lib/types/analytics";

	// ── Derived state from workspace ────────────────────────────────
	let attribution = $derived(workspace.attribution);
	let driftAlerts = $derived(workspace.driftAlerts);
	let factorData = $derived(workspace.localFactorAnalysis);
	let riskBudget = $derived(workspace.riskBudget);

	let isLoadingAttribution = $derived(workspace.isLoadingAttribution);
	let isLoadingDrift = $derived(workspace.isLoadingDrift);
	let isLoadingFactor = $derived(workspace.isLoadingFactorAnalysis);
	let isLoadingRiskBudget = $derived(workspace.isLoadingRiskBudget);

	let hasPortfolio = $derived(workspace.portfolio != null);

	// ── Attribution ECharts ─────────────────────────────────────────
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
			legend: {
				data: ["Allocation", "Selection"],
				bottom: 0,
				textStyle: { color: "#85a0bd", fontSize: 11 },
			},
			grid: { containLabel: true, left: 16, right: 24, top: 12, bottom: 36 },
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: (v: number) => `${v} bps`, fontSize: 10, color: "#85a0bd" },
				splitLine: { lineStyle: { color: "rgba(64,66,73,0.3)", type: "dashed" as const } },
			},
			yAxis: {
				type: "category" as const,
				data: names,
				axisLabel: { width: 120, overflow: "truncate" as const, fontSize: 11, color: "#cbccd1" },
			},
			series: [
				{
					name: "Allocation",
					type: "bar" as const,
					data: allocData,
					itemStyle: { color: "#11ec79", borderRadius: [0, 2, 2, 0] },
				},
				{
					name: "Selection",
					type: "bar" as const,
					data: selData,
					itemStyle: { color: "#0194ff", borderRadius: [0, 2, 2, 0] },
				},
			],
		} as Record<string, unknown>;
	});

	// ── Factor Analysis Donut ───────────────────────────────────────
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
			...globalChartOptions,
			toolbox: { show: false },
			tooltip: { ...globalChartOptions.tooltip, trigger: "item" as const },
			legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: '#85a0bd' } },
			series: [{
				type: "pie" as const,
				radius: ["50%", "72%"],
				center: ["50%", "44%"],
				label: { show: false },
				labelLine: { show: false },
				itemStyle: { borderColor: '#141519', borderWidth: 2, borderRadius: 4 },
				emphasis: { label: { show: true, fontSize: 12, fontWeight: 700, color: '#fff' } },
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
			...globalChartOptions,
			toolbox: { show: false },
			grid: { left: 110, right: 40, top: 8, bottom: 24, containLabel: false },
			tooltip: { ...globalChartOptions.tooltip, trigger: "axis" as const, axisPointer: { type: 'shadow' } },
			xAxis: {
				type: "value" as const, min: -1, max: 1,
				axisLabel: { formatter: "{value}", fontSize: 10, color: '#85a0bd' },
				splitLine: { lineStyle: { type: "dashed" as const, color: 'rgba(64,66,73,0.3)' } },
			},
			yAxis: {
				type: "category" as const, data: categories, inverse: true,
				axisLabel: { fontSize: 11, fontWeight: 600, color: '#cbccd1' },
				axisTick: { show: false }, axisLine: { show: false },
			},
			series: [{
				type: "bar" as const, barWidth: "40%",
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
					show: true, position: "right" as const, fontSize: 10, fontWeight: 600, color: '#fff',
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

	// ── Helpers ──────────────────────────────────────────────────────
	function fmtBps(v: number): string {
		return formatBps(v, { decimals: 1, signed: true });
	}
</script>

{#if !hasPortfolio}
	<div class="arp-empty">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to view analytics & risk."
		/>
	</div>
{:else}
	<div class="arp-root">

		<!-- ═══ Section 1: Attribution (Brinson-Fachler) ═══ -->
		<div class="arp-section">
			<div class="arp-section-header">
				<div class="arp-icon-wrap arp-icon--blue">
					<TrendingUp class="h-4 w-4 text-[#0177fb]" />
				</div>
				<span class="arp-section-title">Brinson-Fachler Attribution</span>
			</div>

			{#if isLoadingAttribution}
				<div class="arp-loading">
					<Loader2 class="h-5 w-5 animate-spin text-[#0177fb]" />
					<span>Loading attribution...</span>
				</div>
			{:else if attribution}
				<!-- KPI row -->
				<div class="arp-kpi-row">
					<div class="arp-kpi">
						<span class="arp-kpi-label">Portfolio</span>
						<span class="arp-kpi-value">{formatPercent(attribution.total_portfolio_return)}</span>
					</div>
					<div class="arp-kpi">
						<span class="arp-kpi-label">Benchmark</span>
						<span class="arp-kpi-value">{formatPercent(attribution.total_benchmark_return)}</span>
					</div>
					<div class="arp-kpi">
						<span class="arp-kpi-label">Excess</span>
						<span class="arp-kpi-value" style:color={effectColor(attribution.total_excess_return)}>
							{fmtBps(attribution.total_excess_return)}
						</span>
					</div>
					<div class="arp-kpi">
						<span class="arp-kpi-label">Allocation</span>
						<span class="arp-kpi-value" style:color={effectColor(attribution.allocation_total)}>
							{fmtBps(attribution.allocation_total)}
						</span>
					</div>
					<div class="arp-kpi">
						<span class="arp-kpi-label">Selection</span>
						<span class="arp-kpi-value" style:color={effectColor(attribution.selection_total)}>
							{fmtBps(attribution.selection_total)}
						</span>
					</div>
				</div>

				<!-- Attribution chart -->
				{#if attributionChartOption}
					<div class="arp-chart-wrap">
						<ChartContainer
							option={attributionChartOption}
							height={Math.max(180, sectors.length * 36 + 48)}
							ariaLabel="Attribution by sector"
						/>
					</div>
				{:else}
					<p class="arp-hint">Attribution requires at least 2 periods of performance data.</p>
				{/if}
			{:else}
				<p class="arp-hint">No attribution data available for this portfolio profile.</p>
			{/if}
		</div>

		<!-- ═══ Section 2: Factor Analysis ═══ -->
		<div class="arp-section">
			<div class="arp-section-header">
				<div class="arp-icon-wrap arp-icon--purple">
					<PieChart class="h-4 w-4 text-[#a855f7]" />
				</div>
				<span class="arp-section-title">Factor Analysis</span>
				{#if factorData}
					<div class="arp-badge-row">
						<span class="arp-badge">R² {formatNumber(factorData.r_squared, 3, "en-US")}</span>
						<span class="arp-badge">Systematic {formatPercent(factorData.systematic_risk_pct / 100, 1, "en-US")}</span>
					</div>
				{/if}
			</div>

			{#if isLoadingFactor}
				<div class="arp-loading">
					<Loader2 class="h-5 w-5 animate-spin text-[#a855f7]" />
					<span>Running factor analysis...</span>
				</div>
			{:else if factorData}
				<div class="arp-factor-grid">
					<div class="arp-factor-cell">
						<span class="arp-cell-label">Risk Decomposition</span>
						<ChartContainer option={donutOption} height={200} ariaLabel="Risk decomposition donut" />
					</div>
					<div class="arp-factor-cell">
						<span class="arp-cell-label">Style Factor Exposures</span>
						<ChartContainer option={barOption} height={200} ariaLabel="Style factor exposures" />
					</div>
				</div>
			{:else}
				<p class="arp-hint">No factor analysis available. Construct the portfolio first.</p>
			{/if}
		</div>

		<!-- ═══ Section 3: Strategy Drift ═══ -->
		<div class="arp-section">
			<div class="arp-section-header">
				<div class="arp-icon-wrap arp-icon--amber">
					<ShieldAlert class="h-4 w-4 text-[#f59e0b]" />
				</div>
				<span class="arp-section-title">Strategy Drift</span>
				{#if driftAlerts.length > 0}
					<span class="arp-drift-count">{driftAlerts.length}</span>
				{/if}
			</div>

			{#if isLoadingDrift}
				<div class="arp-loading">
					<Loader2 class="h-5 w-5 animate-spin text-[#f59e0b]" />
					<span>Loading drift alerts...</span>
				</div>
			{:else if driftAlerts.length > 0}
				<div class="arp-drift-list">
					{#each driftAlerts.slice(0, 10) as alert (alert.instrument_id)}
						<div class="arp-drift-row">
							<span class="arp-drift-name">{alert.instrument_name}</span>
							<span class="arp-drift-severity" style:color={severityColor(alert.severity)}>
								{alert.severity}
							</span>
							<span class="arp-drift-meta">{alert.anomalous_count}/{alert.total_metrics} metrics</span>
						</div>
					{/each}
					{#if driftAlerts.length > 10}
						<p class="arp-hint" style="padding: 8px 16px;">+{driftAlerts.length - 10} more alerts</p>
					{/if}
				</div>
			{:else}
				<p class="arp-hint">No drift alerts detected. Instruments are behaving within baseline.</p>
			{/if}
		</div>

		<!-- ═══ Section 4: Risk Budget (on-demand) ═══ -->
		<div class="arp-section">
			<div class="arp-section-header">
				<div class="arp-icon-wrap arp-icon--green">
					<Scale class="h-4 w-4 text-[#22c55e]" />
				</div>
				<span class="arp-section-title">Risk Budget</span>
				{#if !riskBudget}
					<Button
						size="sm"
						variant="outline"
						disabled={isLoadingRiskBudget}
						onclick={() => workspace.loadRiskBudget()}
						class="h-7 text-[11px] ml-auto"
					>
						{isLoadingRiskBudget ? "Loading..." : "Compute"}
					</Button>
				{/if}
			</div>

			{#if isLoadingRiskBudget}
				<div class="arp-loading">
					<Loader2 class="h-5 w-5 animate-spin text-[#22c55e]" />
					<span>Computing risk budget...</span>
				</div>
			{:else if riskBudget}
				<div class="arp-kpi-row">
					<div class="arp-kpi">
						<span class="arp-kpi-label">Portfolio Vol</span>
						<span class="arp-kpi-value">{formatPercent(riskBudget.portfolio_volatility)}</span>
					</div>
					<div class="arp-kpi">
						<span class="arp-kpi-label">Portfolio ETL</span>
						<span class="arp-kpi-value">{formatPercent(riskBudget.portfolio_etl)}</span>
					</div>
					{#if riskBudget.portfolio_starr != null}
						<div class="arp-kpi">
							<span class="arp-kpi-label">STARR</span>
							<span class="arp-kpi-value">{formatNumber(riskBudget.portfolio_starr, 3, "en-US")}</span>
						</div>
					{/if}
				</div>
				<div class="arp-rb-table">
					<div class="arp-rb-header">
						<span>Block</span><span>Weight</span><span>MCTR</span><span>PCTR</span>
					</div>
					{#each riskBudget.funds as fund (fund.block_id)}
						<div class="arp-rb-row">
							<span class="arp-rb-name">{fund.block_name}</span>
							<span class="arp-rb-val">{formatPercent(fund.weight)}</span>
							<span class="arp-rb-val">{fund.mctr != null ? formatPercent(fund.mctr) : "—"}</span>
							<span class="arp-rb-val">{fund.pctr != null ? formatPercent(fund.pctr) : "—"}</span>
						</div>
					{/each}
				</div>
			{:else}
				<p class="arp-hint">Click Compute to run risk budget decomposition for this portfolio.</p>
			{/if}
		</div>
	</div>
{/if}

<style>
	.arp-root {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 20px;
		height: 100%;
	}

	.arp-empty {
		padding: 48px 24px;
	}

	/* ── Section card ── */
	.arp-section {
		background: rgba(255, 255, 255, 0.015);
		border: 1px solid rgba(64, 66, 73, 0.3);
		border-radius: 20px;
		overflow: hidden;
	}

	.arp-section-header {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 14px 20px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.2);
	}

	.arp-icon-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.arp-icon--blue { background: rgba(1, 119, 251, 0.12); border: 1px solid rgba(1, 119, 251, 0.25); }
	.arp-icon--purple { background: rgba(168, 85, 247, 0.12); border: 1px solid rgba(168, 85, 247, 0.25); }
	.arp-icon--amber { background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.25); }
	.arp-icon--green { background: rgba(34, 197, 94, 0.12); border: 1px solid rgba(34, 197, 94, 0.25); }

	.arp-section-title {
		font-size: 15px;
		font-weight: 700;
		color: #fff;
		letter-spacing: -0.01em;
	}

	.arp-badge-row {
		display: flex;
		gap: 6px;
		margin-left: auto;
	}

	.arp-badge {
		font-size: 11px;
		font-weight: 600;
		color: #85a0bd;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.08);
		padding: 2px 8px;
		border-radius: 999px;
	}

	/* ── KPI row ── */
	.arp-kpi-row {
		display: flex;
		gap: 1px;
		margin: 0 16px;
		background: rgba(64, 66, 73, 0.3);
		border-radius: 12px;
		overflow: hidden;
	}

	.arp-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 10px 14px;
		flex: 1;
		background: #141519;
	}

	.arp-kpi-label {
		font-size: 11px;
		color: #85a0bd;
		font-weight: 500;
	}

	.arp-kpi-value {
		font-size: 14px;
		font-weight: 700;
		color: #fff;
		font-variant-numeric: tabular-nums;
	}

	/* ── Chart ── */
	.arp-chart-wrap {
		padding: 12px 16px 16px;
	}

	/* ── Factor grid ── */
	.arp-factor-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		background: rgba(64, 66, 73, 0.15);
	}

	.arp-factor-cell {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 16px;
		background: #141519;
	}

	.arp-cell-label {
		font-size: 11px;
		font-weight: 600;
		color: #85a0bd;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	/* ── Drift list ── */
	.arp-drift-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 20px;
		height: 20px;
		padding: 0 6px;
		border-radius: 10px;
		background: #f59e0b;
		color: #000;
		font-size: 11px;
		font-weight: 700;
	}

	.arp-drift-list {
		display: flex;
		flex-direction: column;
	}

	.arp-drift-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 20px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.2);
		font-size: 13px;
	}

	.arp-drift-row:last-child {
		border-bottom: none;
	}

	.arp-drift-name {
		flex: 1;
		color: #cbccd1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.arp-drift-severity {
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.02em;
	}

	.arp-drift-meta {
		font-size: 12px;
		color: #71717a;
		font-variant-numeric: tabular-nums;
	}

	/* ── Risk budget table ── */
	.arp-rb-table {
		padding: 0 16px 12px;
	}

	.arp-rb-header {
		display: grid;
		grid-template-columns: 1fr 80px 80px 80px;
		gap: 8px;
		padding: 6px 0;
		font-size: 11px;
		font-weight: 600;
		color: #71717a;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
	}

	.arp-rb-row {
		display: grid;
		grid-template-columns: 1fr 80px 80px 80px;
		gap: 8px;
		padding: 6px 0;
		font-size: 13px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.15);
	}

	.arp-rb-name {
		color: #cbccd1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.arp-rb-val {
		color: #fff;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	/* ── Shared ── */
	.arp-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 32px 16px;
		color: #85a0bd;
		font-size: 13px;
		font-weight: 500;
	}

	.arp-hint {
		padding: 24px 20px;
		text-align: center;
		color: #71717a;
		font-size: 13px;
		margin: 0;
	}
</style>

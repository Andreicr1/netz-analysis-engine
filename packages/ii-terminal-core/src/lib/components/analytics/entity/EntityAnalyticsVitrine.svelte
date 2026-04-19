<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { createClientApiClient } from "../../../api/client";
	import ScoreCompositionPanel from "./ScoreCompositionPanel.svelte";

	interface Props {
		id: string;
	}

	let { id }: Props = $props();

	// Component State
	let data = $state<any>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Auth-aware API client — fixes X2 smoke regression where the
	// terminal app (different dev port) hit its own origin on a
	// relative /api/v1 path and 404'd. api-client resolves against
	// VITE_API_BASE_URL and attaches the Clerk bearer token.
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// Fetch Data
	$effect(() => {
		if (!id) return;
		loading = true;
		error = null;

		api
			.get<any>(`/wealth/entity-analytics/${id}`)
			.then(d => {
				data = d;
				loading = false;
			})
			.catch(e => {
				error = e instanceof Error ? e.message : String(e);
				loading = false;
			});
	});

	// Formatting helper
	function f(val: number | null | undefined, fmt: 'percent' | 'decimal' | 'bps' = 'decimal', decimals = 2) {
		if (val == null) return "-";
		if (fmt === 'percent') return formatNumber(val * 100, decimals) + "%";
		if (fmt === 'bps') return formatNumber(val * 10000, 0);
		return formatNumber(val, decimals);
	}

	function f_mil(val: number | null | undefined): string {
		if (val == null) return "-";
		return formatNumber(val / 1000000, 2);
	}

	// Base ECharts Configuration — cinematic reactor animation
	const baseChartOptions = {
		backgroundColor: "transparent",
		animation: true,
		animationDuration: 1500,
		animationEasing: "cubicOut",
		animationDelay: (idx: number) => idx * 10,
		grid: { top: "10%", bottom: "10%", left: "10%", right: "5%" },
		tooltip: {
			trigger: "axis",
			axisPointer: { type: "cross", crossStyle: { color: "#666" } },
			backgroundColor: "#000",
			borderColor: "#333",
			borderWidth: 1,
			textStyle: { fontFamily: "monospace", fontSize: 11, color: "#fff" },
			borderRadius: 0,
		},
		textStyle: { fontFamily: "monospace" },
		xAxis: {
			axisLabel: { fontFamily: "monospace", fontSize: 10, color: "#9ca3af" },
			splitLine: { show: true, lineStyle: { type: "dashed", color: "#333", width: 1 } },
			axisLine: { lineStyle: { color: "#444" } }
		},
		yAxis: {
			axisLabel: { fontFamily: "monospace", fontSize: 10, color: "#9ca3af" },
			splitLine: { show: true, lineStyle: { type: "dashed", color: "#333", width: 1 } },
			axisLine: { lineStyle: { color: "#444" } }
		}
	};

	// Drawdown Analysis Options
	let drawdownOption = $derived.by(() => {
		if (!data?.drawdown?.series) return null;
		return {
			...baseChartOptions,
			xAxis: { ...baseChartOptions.xAxis, type: "category", data: data.drawdown.dates || [] },
			yAxis: { ...baseChartOptions.yAxis, type: "value", max: 0 },
			series: [{
				type: "line",
				data: data.drawdown.series,
				areaStyle: { color: "rgba(220, 38, 38, 0.2)" }, // Red translucent
				lineStyle: { color: "#dc2626", width: 1 },
				symbol: "none",
				step: false
			}]
		};
	});

	// Capture Ratios Options
	let captureOption = $derived.by(() => {
		if (!data?.capture?.down || !data?.capture?.up) return null;
		return {
			...baseChartOptions,
			tooltip: {
				...baseChartOptions.tooltip,
				trigger: "item",
				formatter: (p: any) => `Down: ${p.value[0]}<br/>Up: ${p.value[1]}`
			},
			xAxis: { ...baseChartOptions.xAxis, type: "value", name: "Down Capture", nameLocation: "middle", nameGap: 20, nameTextStyle: { fontSize: 10, fontFamily: "monospace" } },
			yAxis: { ...baseChartOptions.yAxis, type: "value", name: "Up Capture", nameLocation: "middle", nameGap: 30, nameTextStyle: { fontSize: 10, fontFamily: "monospace" } },
			series: [
				{
					type: "scatter",
					data: [[data.capture.down, data.capture.up]],
					symbolSize: 8,
					itemStyle: { color: "#fff" }
				},
				{
					type: "line",
					data: [[0, 0], [200, 200]],
					lineStyle: { color: "#555", type: "dashed", width: 1 },
					symbol: "none",
					silent: true
				}
			]
		};
	});

	// Rolling Returns Options
	let rollingOption = $derived.by(() => {
		if (!data?.rolling) return null;
		return {
			...baseChartOptions,
			legend: { show: true, textStyle: { color: "#fff", fontFamily: "monospace", fontSize: 10 }, icon: "rect" },
			xAxis: { ...baseChartOptions.xAxis, type: "category", data: data.rolling.dates || [] },
			yAxis: { ...baseChartOptions.yAxis, type: "value" },
			series: [
				{ name: "3m", type: "line", data: data.rolling.series_3m, smooth: false, symbol: "none", lineStyle: { width: 1 } },
				{ name: "6m", type: "line", data: data.rolling.series_6m, smooth: false, symbol: "none", lineStyle: { width: 1 } },
				{ name: "1y", type: "line", data: data.rolling.series_1y, smooth: false, symbol: "none", lineStyle: { width: 1 } }
			]
		};
	});

	// Return Distribution Options
	let distributionOption = $derived.by(() => {
		if (!data?.distribution) return null;
		return {
			...baseChartOptions,
			xAxis: { ...baseChartOptions.xAxis, type: "category", data: data.distribution.bins || [] },
			yAxis: { ...baseChartOptions.yAxis, type: "value" },
			series: [{
				type: "bar",
				data: data.distribution.frequencies || [],
				itemStyle: { color: "#4b5563", borderRadius: 0 },
				markLine: {
					symbol: "none",
					data: [
						{ xAxis: data.distribution.var_95?.toString() || "", lineStyle: { color: "#ef4444", type: "solid" }, label: { formatter: "VaR", color: "#ef4444", fontSize: 9 } },
						{ xAxis: data.distribution.cvar_95?.toString() || "", lineStyle: { color: "#b91c1c", type: "dashed" }, label: { formatter: "CVaR", color: "#b91c1c", fontSize: 9 } }
					]
				}
			}]
		};
	});

</script>

<div class="vitrine-wrapper">
	<!-- TAIL RISK STRIP (Header) -->
	<header class="tail-strip">
		<div class="strip-item">
			<span class="label">STARR</span>
			<span class="value">{f(data?.tail?.starr, 'decimal', 3)}</span>
		</div>
		<div class="strip-item">
			<span class="label">Rachev Ratio</span>
			<span class="value">{f(data?.tail?.rachev, 'decimal', 3)}</span>
		</div>
		<div class="strip-item">
			<span class="label">ETL 95%</span>
			<span class="value">{f(data?.tail?.etl_95, 'percent', 2)}</span>
		</div>
		<div class="strip-item">
			<span class="label">JB p-value</span>
			<span class="value">{f(data?.tail?.jb_p_value, 'decimal', 4)}</span>
		</div>
	</header>

	{#if loading}
		<div class="status-box">LOADING ENTITY DNA...</div>
	{:else if error}
		<div class="status-box text-red-500">ERR: {error}</div>
	{:else}
		<main class="grid-layout">

			<!-- 0. Score Composition (first module — answers "is this fund good and WHY") -->
			<ScoreCompositionPanel {id} />

			<!-- 1. Risk Statistics Table -->
			<section class="module">
				<h2 class="module-title">RISK STATISTICS</h2>
				<table class="data-table">
					<tbody>
						<tr><td>Beta</td><td class="num">{f(data?.risk?.beta)}</td></tr>
						<tr><td>Alpha</td><td class="num">{f(data?.risk?.alpha, 'bps')} bps</td></tr>
						<tr><td>Tracking Error</td><td class="num">{f(data?.risk?.tracking_error, 'percent')}</td></tr>
						<tr><td>Calmar Ratio</td><td class="num">{f(data?.risk?.calmar)}</td></tr>
						<tr><td>Sharpe Ratio</td><td class="num">{f(data?.risk?.sharpe)}</td></tr>
						<tr><td>Sortino Ratio</td><td class="num">{f(data?.risk?.sortino)}</td></tr>
					</tbody>
				</table>
			</section>

			<!-- 2. Drawdown Analysis -->
			<section class="module">
				<h2 class="module-title">UNDERWATER DRAWDOWN</h2>
				<div class="chart-wrapper">
					{#if drawdownOption}
						<ChartContainer option={drawdownOption} height={150} ariaLabel="Drawdown Chart" />
					{:else}
						<div class="empty-state">-</div>
					{/if}
				</div>
				<table class="data-table mt-2">
					<thead>
						<tr><th>Depth</th><th>Duration</th><th>Recovery</th></tr>
					</thead>
					<tbody>
						{#each (data?.drawdown?.worst_periods || []).slice(0,3) as period}
							<tr>
								<td class="num">{f(period.depth, 'percent')}</td>
								<td class="num">{period.duration || "-"}d</td>
								<td class="num">{period.recovery || "-"}d</td>
							</tr>
						{/each}
						{#if !data?.drawdown?.worst_periods?.length}
							<tr><td colspan="3" class="text-center">-</td></tr>
						{/if}
					</tbody>
				</table>
			</section>

			<!-- 3. Capture Ratios -->
			<section class="module">
				<h2 class="module-title">CAPTURE RATIOS</h2>
				<div class="chart-wrapper">
					{#if captureOption}
						<ChartContainer option={captureOption} height={200} ariaLabel="Capture Ratios Scatter" />
					{:else}
						<div class="empty-state">-</div>
					{/if}
				</div>
			</section>

			<!-- 4. Rolling Returns -->
			<section class="module">
				<h2 class="module-title">ROLLING RETURNS</h2>
				<div class="chart-wrapper">
					{#if rollingOption}
						<ChartContainer option={rollingOption} height={200} ariaLabel="Rolling Returns Chart" />
					{:else}
						<div class="empty-state">-</div>
					{/if}
				</div>
			</section>

			<!-- 5. Return Distribution -->
			<section class="module">
				<h2 class="module-title">RETURN DISTRIBUTION</h2>
				<div class="chart-wrapper">
					{#if distributionOption}
						<ChartContainer option={distributionOption} height={200} ariaLabel="Return Distribution Histogram" />
					{:else}
						<div class="empty-state">-</div>
					{/if}
				</div>
			</section>

			<!-- 6. eVestment Statistics -->
			<section class="module evestment">
				<h2 class="module-title">EVESTMENT GRID</h2>
				<div class="ev-grid">
					<div class="ev-group">
						<div class="ev-group-title">Absolute Return</div>
						<div class="ev-row"><span>Ann. Return</span><span class="num">{f(data?.evestment?.abs_return?.annualized, 'percent')}</span></div>
						<div class="ev-row"><span>Best Month</span><span class="num">{f(data?.evestment?.abs_return?.best_month, 'percent')}</span></div>
					</div>
					<div class="ev-group">
						<div class="ev-group-title">Absolute Risk</div>
						<div class="ev-row"><span>Ann. Risk</span><span class="num">{f(data?.evestment?.abs_risk?.annualized, 'percent')}</span></div>
						<div class="ev-row"><span>Max Drawdown</span><span class="num">{f(data?.evestment?.abs_risk?.max_dd, 'percent')}</span></div>
					</div>
					<div class="ev-group">
						<div class="ev-group-title">Risk-Adjusted</div>
						<div class="ev-row"><span>Info Ratio</span><span class="num">{f(data?.evestment?.risk_adj?.info_ratio)}</span></div>
						<div class="ev-row"><span>Treynor</span><span class="num">{f(data?.evestment?.risk_adj?.treynor)}</span></div>
					</div>
					<div class="ev-group">
						<div class="ev-group-title">Proficiency & Regr.</div>
						<div class="ev-row"><span>Up/Down Ratio</span><span class="num">{f(data?.evestment?.proficiency?.up_down_ratio)}</span></div>
						<div class="ev-row"><span>R-Squared</span><span class="num">{f(data?.evestment?.regression?.r_squared)}</span></div>
					</div>
				</div>
			</section>

			<!-- 7. Alternative Data: Insider Sentiment -->
			<section class="module">
				<h2 class="module-title">[ ALTERNATIVE DATA: INSIDER SENTIMENT ]</h2>
				<div class="flex-1 flex flex-col justify-center items-center gap-4 py-4 h-full min-h-[150px]">
					{#if !data?.insider_data || data?.insider_data?.insider_sentiment_score === 50.0 || data?.insider_data?.insider_sentiment_score == null}
						<span class="text-gray-500 font-mono text-center">NO MATERIAL INSIDER ACTIVITY</span>
					{:else}
						{@const score = data.insider_data.insider_sentiment_score}
						{#if score < 40}
							<span class="text-[#ef4444] font-mono animate-pulse text-center">[ HEAVY DISTRIBUTION ]</span>
						{:else if score > 60}
							<span class="text-[#22c55e] font-mono text-center">[ ACCUMULATION ]</span>
						{:else}
							<span class="text-gray-300 font-mono text-center">[ NEUTRAL FLOW ]</span>
						{/if}
						<div class="w-full flex flex-col gap-2 mt-4 text-xs font-mono" style="max-width: 200px;">
							<div class="flex justify-between border-b border-dotted border-[#222] pb-1">
								<span class="text-gray-500">BUY VOL:</span>
								<span class="text-gray-300 text-right w-24">$ {f_mil(data.insider_data.insider_summary?.buy_value)} M</span>
							</div>
							<div class="flex justify-between">
								<span class="text-gray-500">SELL VOL:</span>
								<span class="text-gray-300 text-right w-24">$ {f_mil(data.insider_data.insider_summary?.sell_value)} M</span>
							</div>
						</div>
					{/if}
				</div>
			</section>

		</main>
	{/if}
</div>

<style>
	/* Brutalist Design System - Financial Quant */
	.vitrine-wrapper {
		background-color: #000;
		color: #e5e7eb;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
		font-size: 0.75rem; /* text-xs */
		display: flex;
		flex-direction: column;
		border: 1px solid #333;
	}

	.tail-strip {
		display: flex;
		flex-wrap: wrap;
		border-bottom: 1px solid #333;
		background-color: #0a0a0a;
	}

	.strip-item {
		flex: 1;
		min-width: 120px;
		display: flex;
		flex-direction: column;
		padding: 8px 12px;
		border-right: 1px solid #333;
	}

	.strip-item:last-child {
		border-right: none;
	}

	.strip-item .label {
		color: #6b7280;
		text-transform: uppercase;
		font-size: 0.65rem;
		letter-spacing: 0.05em;
	}

	.strip-item .value {
		font-size: 0.875rem; /* text-sm */
		font-weight: 700;
		color: #f3f4f6;
		margin-top: 2px;
	}

	.status-box {
		padding: 24px;
		text-align: center;
		color: #9ca3af;
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	/* CSS Grid responsive with 1px gap acting as hard borders */
	.grid-layout {
		display: grid;
		grid-template-columns: 1fr;
		gap: 1px;
		background-color: #333; /* border color */
	}

	@media (min-width: 768px) {
		.grid-layout { grid-template-columns: repeat(2, 1fr); }
	}

	@media (min-width: 1280px) {
		.grid-layout { grid-template-columns: repeat(3, 1fr); }
	}

	.module {
		background-color: #000;
		padding: 16px;
		display: flex;
		flex-direction: column;
	}

	.module-title {
		font-size: 0.7rem;
		font-weight: 700;
		color: #9ca3af;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: 12px;
		border-bottom: 1px solid #222;
		padding-bottom: 4px;
	}

	.data-table {
		width: 100%;
		border-collapse: collapse;
	}

	.data-table th, .data-table td {
		padding: 6px 0;
		border-bottom: 1px solid #111;
		color: #d1d5db;
	}

	.data-table th {
		text-align: left;
		color: #6b7280;
		font-weight: normal;
		font-size: 0.65rem;
		text-transform: uppercase;
	}

	.data-table .num {
		text-align: right;
	}

	.data-table tbody tr:last-child td {
		border-bottom: none;
	}

	.chart-wrapper {
		flex: 1;
		min-height: 150px;
		display: flex;
		flex-direction: column;
		justify-content: center;
	}

	.empty-state {
		text-align: center;
		color: #4b5563;
	}

	/* eVestment Grid */
	.ev-grid {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.ev-group-title {
		color: #6b7280;
		font-size: 0.65rem;
		text-transform: uppercase;
		margin-bottom: 4px;
	}

	.ev-row {
		display: flex;
		justify-content: space-between;
		padding: 4px 0;
		border-bottom: 1px dotted #222;
	}
	
	.ev-row:last-child {
		border-bottom: none;
	}

	.ev-row .num {
		text-align: right;
		color: #d1d5db;
	}

	.mt-2 { margin-top: 8px; }
	.text-center { text-align: center; }
	.text-red-500 { color: #ef4444; }

	/* Spanning rules for larger items if needed */
	.evestment {
		grid-row: span 2;
	}
</style>
<!--
  FactorAnalysisPanel — Risk decomposition (donut) + Style factor exposures (horizontal bar).
  Mock deterministic data derived from workspace.funds for reactivity.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { EmptyState } from "@investintell/ui";
	import PieChart from "lucide-svelte/icons/pie-chart";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	// ── Seed from fund count for deterministic variance ─────────────────
	let fundCount = $derived(workspace.funds.length);

	// ── Risk Decomposition (Donut) ──────────────────────────────────────
	let donutOption = $derived.by(() => {
		if (fundCount === 0) return {};

		// Deterministic: shift systematic risk slightly based on fund count
		const systematic = 72 + (fundCount % 5) * 1.2;
		const style = 14 + (fundCount % 3) * 0.8;
		const idiosyncratic = +(100 - systematic - style).toFixed(1);

		return {
			...globalChartOptions,
			toolbox: { show: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "item" as const,
				formatter: (p: { name?: string; value?: number; percent?: number; marker?: string }) =>
					`${p.marker ?? ""} ${p.name}<br/><strong>${p.percent?.toFixed(1)}%</strong> of total risk`,
			},
			legend: {
				bottom: 0,
				itemWidth: 10,
				itemHeight: 10,
				textStyle: { fontSize: 11 },
			},
			series: [
				{
					name: "Risk Decomposition",
					type: "pie" as const,
					radius: ["40%", "65%"],
					center: ["50%", "45%"],
					avoidLabelOverlap: true,
					label: { show: false },
					emphasis: {
						label: { show: true, fontSize: 12, fontWeight: 600 },
					},
					data: [
						{ value: systematic, name: "Systematic (Market)", itemStyle: { color: "#0177fb" } },
						{ value: style, name: "Style Factors", itemStyle: { color: "#11ec79" } },
						{ value: idiosyncratic, name: "Idiosyncratic", itemStyle: { color: "#d29922" } },
					],
				},
			],
		};
	});

	// ── Style Exposures (Horizontal Bar) ────────────────────────────────
	let barOption = $derived.by(() => {
		if (fundCount === 0) return {};

		// Deterministic factor exposures seeded by fund count
		const seed = fundCount * 7;
		const factors = [
			{ name: "Value", exposure: 0.32 - (seed % 5) * 0.04 },
			{ name: "Momentum", exposure: -0.18 + (seed % 3) * 0.06 },
			{ name: "Quality", exposure: 0.25 - (seed % 4) * 0.03 },
			{ name: "Size", exposure: -0.12 + (seed % 6) * 0.02 },
			{ name: "Low Volatility", exposure: 0.15 + (seed % 2) * 0.05 },
		];

		const categories = factors.map((f) => f.name);
		const values = factors.map((f) => Math.round(f.exposure * 1000) / 1000);

		return {
			...globalChartOptions,
			toolbox: { show: false },
			grid: { left: 110, right: 40, top: 8, bottom: 24, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "axis" as const,
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number; marker?: string };
					if (p.value == null) return "";
					return `<strong>${p.name}</strong><br/>${p.marker ?? ""} Exposure: ${p.value > 0 ? "+" : ""}${p.value.toFixed(3)}`;
				},
			},
			xAxis: {
				type: "value" as const,
				min: -1,
				max: 1,
				axisLabel: { formatter: "{value}", fontSize: 11 },
				splitLine: { lineStyle: { type: "dashed" as const } },
			},
			yAxis: {
				type: "category" as const,
				data: categories,
				inverse: true,
				axisLabel: { fontSize: 12, fontWeight: 600 },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Exposure",
					type: "bar" as const,
					data: values.map((v) => ({
						value: v,
						itemStyle: {
							color: v >= 0 ? "#11ec79" : "#fc1a1a",
							borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
						},
					})),
					barWidth: "50%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 11,
						fontWeight: 600,
						formatter: (p: { value: number }) => `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}`,
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: "var(--ii-text-muted)", type: "solid" as const, width: 1 },
						label: { show: false },
					},
				},
			],
		};
	});

	let hasFunds = $derived(fundCount > 0);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to view factor analysis."
		/>
	</div>
{:else if !hasFunds}
	<div class="p-6">
		<EmptyState
			title="No funds in portfolio"
			message="Add funds to the portfolio to generate factor decomposition."
		/>
	</div>
{:else}
	<div class="factor-panel">
		<div class="factor-header">
			<PieChart class="h-4 w-4" style="color: var(--ii-chart-1, #0177fb);" />
			<span class="factor-title">Factor Analysis</span>
			<span class="factor-subtitle">{fundCount} fund{fundCount !== 1 ? "s" : ""}</span>
		</div>

		<div class="factor-grid">
			<!-- Donut: Risk Decomposition -->
			<div class="factor-section">
				<span class="section-label">Risk Decomposition</span>
				<ChartContainer
					option={donutOption}
					height={220}
					empty={!hasFunds}
					ariaLabel="Risk decomposition donut chart"
				/>
			</div>

			<!-- Horizontal Bar: Style Exposures -->
			<div class="factor-section">
				<span class="section-label">Style Factor Exposures</span>
				<ChartContainer
					option={barOption}
					height={220}
					empty={!hasFunds}
					ariaLabel="Style factor exposures bar chart"
				/>
			</div>
		</div>
	</div>
{/if}

<style>
	.factor-panel {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 16px;
		height: 100%;
	}

	.factor-header {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.factor-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.factor-subtitle {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		margin-left: auto;
	}

	.factor-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
		flex: 1;
		min-height: 0;
	}

	@media (max-width: 900px) {
		.factor-grid {
			grid-template-columns: 1fr;
		}
	}

	.factor-section {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.section-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
</style>

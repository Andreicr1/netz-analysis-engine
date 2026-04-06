<!--
  FactorAnalysisPanel — Risk decomposition (donut) + Style factor exposures (horizontal bar).
  Live API data integrated.
  Design: dark premium (Figma One X).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { EmptyState } from "@investintell/ui";
	import PieChart from "lucide-svelte/icons/pie-chart";
	import { workspace, type FactorContribution } from "$lib/state/portfolio-workspace.svelte";

	// ── Real API Data Integration ───────────────────────────────────────
	let data = $derived(workspace.localFactorAnalysis);
	let isLoading = $derived(workspace.isLoadingFactorAnalysis);
	let hasData = $derived(data != null);

	// ── Risk Decomposition (Donut) ──────────────────────────────────────
	let donutOption = $derived.by(() => {
		if (!data) return {};

		const systematic = data.systematic_risk_pct * 100;
		const idiosyncratic = data.specific_risk_pct * 100;
		// Typically style factors are grouped into systematic in the API response, 
		// but let's see if we have specific risk vs systematic:
		const style = 0; // If you want to show it based on `data.factor_contributions` or just use 2 slices.
		
		// For the breakdown, let's look at `factor_contributions`:
		const factorSlices = (data.factor_contributions || []).map((fc: FactorContribution) => ({
			value: fc.pct_contribution * 100,
			name: fc.factor_label
		}));
		// If the sum is < 100, we might add idiosyncratic or just show the slices.
		const slices = factorSlices.length > 0 ? factorSlices : [
			{ value: systematic, name: "Systematic (Market)", itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{offset: 0, color: '#0194ff'}, {offset: 1, color: '#0054c2'}] } } },
			{ value: idiosyncratic, name: "Idiosyncratic", itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{offset: 0, color: '#ebb94d'}, {offset: 1, color: '#9d6d13'}] } } },
		];

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
				textStyle: { fontSize: 11, color: '#85a0bd' },
			},
			series: [
				{
					name: "Risk Decomposition",
					type: "pie" as const,
					radius: ["55%", "75%"],
					center: ["50%", "42%"],
					avoidLabelOverlap: true,
					label: { show: false },
					labelLine: { show: false },
					itemStyle: {
						borderColor: '#141519',
						borderWidth: 2,
						borderRadius: 4,
						shadowBlur: 10,
						shadowColor: 'rgba(0, 0, 0, 0.5)'
					},
					emphasis: {
						label: { show: true, fontSize: 13, fontWeight: 700, color: '#ffffff' },
					},
					data: slices.map((slice: { value: number; name: string; itemStyle?: any }, i: number) => {
						if (slice.itemStyle) return slice; // Keep defined ones
						const colors = [
							[{offset: 0, color: '#0194ff'}, {offset: 1, color: '#0054c2'}],
							[{offset: 0, color: '#1ceba7'}, {offset: 1, color: '#0a8844'}],
							[{offset: 0, color: '#ebb94d'}, {offset: 1, color: '#9d6d13'}],
							[{offset: 0, color: '#c418e6'}, {offset: 1, color: '#7a0a91'}],
							[{offset: 0, color: '#ff4d4d'}, {offset: 1, color: '#cc0000'}],
						];
						const color = colors[i % colors.length];
						return {
							...slice,
							itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: color } }
						}
					}),
				},
			],
		};
	});

	// ── Style Exposures (Horizontal Bar) ────────────────────────────────
	let barOption = $derived.by(() => {
		if (!data) return {};

		const exposures = data.portfolio_factor_exposures || {};
		const categories = Object.keys(exposures);
		const values = Object.values(exposures).map((v: unknown) => Math.round((v as number) * 1000) / 1000);

		return {
			...globalChartOptions,
			toolbox: { show: false },
			grid: { left: 110, right: 40, top: 8, bottom: 24, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "axis" as const,
				axisPointer: { type: 'shadow' },
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
				axisLabel: { formatter: "{value}", fontSize: 10, color: '#85a0bd' },
				splitLine: { lineStyle: { type: "dashed" as const, color: 'rgba(64,66,73,0.3)' } },
			},
			yAxis: {
				type: "category" as const,
				data: categories,
				inverse: true,
				axisLabel: { fontSize: 11, fontWeight: 600, color: '#cbccd1' },
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
							color: v >= 0
									? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#09a552'}, {offset: 1, color: '#11ec79'}] }
									: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#fc1a1a'}, {offset: 1, color: '#a30c0c'}] },
							borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
							shadowBlur: 8,
							shadowColor: v >= 0 ? 'rgba(17,236,121,0.2)' : 'rgba(252,26,26,0.2)'
						},
					})),
					barWidth: "40%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						fontWeight: 600,
						color: '#ffffff',
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

	let fundCount = $derived(workspace.funds.length);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to view factor analysis."
		/>
	</div>
{:else if isLoading}
	<div class="flex flex-col items-center justify-center p-12 text-[#85a0bd]">
		<div class="h-8 w-8 animate-spin rounded-full border-2 border-[#0177fb] border-t-transparent mb-4"></div>
		<p class="text-[13px] font-medium animate-pulse">Running Factor Analysis...</p>
	</div>
{:else if !hasData}
	<div class="p-6">
		<EmptyState
			title="No factor data"
			message="No factor analysis results are available for this portfolio."
		/>
	</div>
{:else}
	<div class="flex flex-col gap-6 p-6 h-full">
		<!-- Header -->
		<div class="flex items-center gap-3">
			<div class="flex items-center justify-center h-9 w-9 rounded-full bg-gradient-to-tr from-[#0177fb]/20 to-[#0177fb]/5 border border-[#0177fb]/30 shadow-[0_0_15px_rgba(1,119,251,0.15)] shrink-0">
				<PieChart class="h-4 w-4 text-[#0177fb]" />
			</div>
			<span class="text-[16px] font-bold text-white tracking-tight">Factor Analysis</span>
			<span class="text-[12px] text-[#85a0bd] bg-white/5 border border-white/10 px-2 py-0.5 rounded-full ml-auto">{fundCount} fund{fundCount !== 1 ? "s" : ""}</span>
		</div>

		<!-- Charts grid -->
		<div class="grid grid-cols-2 gap-8 flex-1 min-h-0 bg-white/[0.015] rounded-[20px] border border-[#404249]/30 p-5">
			<div class="flex flex-col gap-3">
				<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.06em]">Risk Decomposition</span>
				<ChartContainer
					option={donutOption}
					height={240}
					empty={!hasData}
					ariaLabel="Risk decomposition donut chart"
				/>
			</div>

			<div class="flex flex-col gap-3">
				<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.06em]">Style Factor Exposures</span>
				<ChartContainer
					option={barOption}
					height={240}
					empty={!hasData}
					ariaLabel="Style factor exposures bar chart"
				/>
			</div>
		</div>
	</div>
{/if}

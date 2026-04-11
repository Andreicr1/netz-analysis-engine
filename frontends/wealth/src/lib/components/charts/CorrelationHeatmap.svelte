<!--
  Correlation Regime Heatmap — divergent RdBu palette, contagion cell highlighting.
  Wraps ChartContainer directly (NOT the @investintell/ui CorrelationHeatmap).
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { ChartContainer } from "@investintell/ui/charts";
	import { echarts } from "@investintell/ui/charts/echarts-setup";
	import { formatNumber } from "@investintell/ui";
	import type { InstrumentCorrelation } from "$lib/types/analytics";

	interface Props {
		matrix: number[][];
		labels: string[];
		contagionPairs?: InstrumentCorrelation[];
		onPairSelect?: (a: string, b: string) => void;
		height?: number;
		ariaLabel?: string;
	}

	let {
		matrix,
		labels,
		contagionPairs = [],
		onPairSelect,
		height = 500,
		ariaLabel = "Correlation regime heatmap",
	}: Props = $props();

	// Build a Set of contagion pair keys for O(1) lookup
	let contagionSet = $derived.by(() => {
		const s = new Set<string>();
		for (const p of contagionPairs) {
			s.add(`${p.instrument_a_name}|${p.instrument_b_name}`);
			s.add(`${p.instrument_b_name}|${p.instrument_a_name}`);
		}
		return s;
	});

	// Read neutral color from CSS for dark mode support
	let neutralColor = $state("#f7f7f7");

	onMount(() => {
		const html = document.documentElement;
		const bg = getComputedStyle(html).getPropertyValue("--ii-surface-elevated").trim();
		if (bg) neutralColor = bg;
	});

	// Build ECharts data array
	let chartData = $derived.by(() => {
		const n = labels.length;
		const data: [number, number, number][] = [];
		for (let yi = 0; yi < n; yi++) {
			for (let xi = 0; xi < n; xi++) {
				const v = matrix[yi]?.[xi] ?? 0;
				data.push([xi, yi, Math.round(v * 1000) / 1000]);
			}
		}
		return data;
	});

	let option = $derived.by(() => {
		const n = labels.length;
		const isLarge = n > 15;

		return {
			tooltip: {
				position: "top",
				formatter: (params: { data: [number, number, number] }) => {
					const [x, y, v] = params.data;
					const labelA = labels[x] ?? String(x);
					const labelB = labels[y] ?? String(y);
					const isContagion = contagionSet.has(`${labelA}|${labelB}`);
					return `${labelA} / ${labelB}: <strong>${formatNumber(v, 3)}</strong>${isContagion ? ' <span style="color:#ef4444">contagion</span>' : ""}`;
				},
			},
			grid: {
				left: 120,
				right: 80,
				top: 20,
				bottom: 100,
			},
			xAxis: {
				type: "category",
				data: labels,
				splitArea: { show: true },
				axisLabel: {
					rotate: 90,
					fontSize: 9,
					interval: 0,
					overflow: "truncate",
					width: 80,
				},
			},
			yAxis: {
				type: "category",
				data: labels,
				splitArea: { show: true },
				axisLabel: {
					fontSize: isLarge ? 9 : 11,
					interval: 0,
					overflow: "truncate",
					width: 80,
				},
			},
			visualMap: {
				min: -1,
				max: 1,
				calculable: true,
				orient: "horizontal",
				left: "center",
				bottom: 0,
				inRange: {
					color: [
						"#053061", "#2166ac", "#92c5de",
						neutralColor,
						"#f4a582", "#d6604d", "#67001f",
					],
				},
				text: ["+1", "\u22121"],
			},
			series: [
				{
					type: "heatmap",
					data: chartData,
					label: { show: false },
					emphasis: {
						itemStyle: {
							shadowBlur: 10,
							shadowColor: "rgba(0,0,0,0.3)",
						},
					},
					itemStyle: {
						borderWidth: 0,
					},
				},
			],
		} as Record<string, unknown>;
	});

	// ── Click handler via getInstanceByDom ────────────────────────────

	let containerEl: HTMLDivElement | undefined = $state();

	$effect(() => {
		if (!containerEl || !onPairSelect) return;
		const imgEl = containerEl.querySelector("[role='img']") as HTMLElement | null;
		if (!imgEl) return;
		const chart = echarts.getInstanceByDom(imgEl);
		if (!chart) return;

		const handler = (params: { componentType?: string; data?: unknown }) => {
			if (params.componentType !== "series") return;
			const d = params.data as [number, number, number] | undefined;
			if (!d) return;
			const [xi, yi] = d;
			if (xi === yi) return;
			const labelA = labels[xi];
			const labelB = labels[yi];
			if (labelA && labelB) onPairSelect!(labelA, labelB);
		};

		chart.on("click", handler);
		return () => chart.off("click", handler);
	});
</script>

<div class="regime-heatmap" bind:this={containerEl}>
	<ChartContainer {option} {height} {ariaLabel} />
</div>

<style>
	.regime-heatmap {
		position: relative;
	}
</style>

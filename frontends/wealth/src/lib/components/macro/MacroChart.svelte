<!--
  MacroChart — ECharts multi-grid with dual Y-axis, dataZoom, mixed-frequency support.
  Main grid 85% + optional sub-chart 15% for volume-style data.
  Spec: WM-S1-01
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatNumber } from "@investintell/ui";
	import type { BaseChartProps } from "@investintell/ui/charts";

	export interface MacroSeries {
		id: string;
		name: string;
		data: [string, number][];
		frequency: "D" | "M" | "Q" | "A";
		yAxisIndex?: number;
		lineStyle?: "solid" | "dashed";
		color?: string;
		subchart?: boolean;
	}

	interface Props extends BaseChartProps {
		series: MacroSeries[];
		fetching?: boolean;
		timeRange?: "1M" | "3M" | "6M" | "1Y" | "2Y";
		onTimeRangeChange?: (range: "1M" | "3M" | "6M" | "1Y" | "2Y") => void;
	}

	let {
		series,
		fetching = false,
		timeRange = "2Y",
		onTimeRangeChange,
		height = 440,
		...rest
	}: Props = $props();

	const TIME_RANGES = ["1M", "3M", "6M", "1Y", "2Y"] as const;

	let hasMixedFrequency = $derived(
		new Set(series.map((s) => s.frequency)).size > 1,
	);
	let hasSubchart = $derived(series.some((s) => s.subchart));
	let showMixedBanner = $state(true);

	function stepForFreq(freq: string): string | false {
		if (freq === "D") return false;
		return "end";
	}

	let option = $derived.by(() => {
		const mainSeries = series.filter((s) => !s.subchart);
		const subSeries = series.filter((s) => s.subchart);
		const mainGridBottom = hasSubchart ? "25%" : "15%";
		const subGridTop = "80%";

		const grids: Record<string, unknown>[] = [
			{ left: 60, right: 140, top: 40, bottom: mainGridBottom, containLabel: false },
		];
		const xAxes: Record<string, unknown>[] = [
			{ type: "time", gridIndex: 0, axisLabel: { fontSize: 10 }, axisTick: { show: false } },
		];
		const yAxes: Record<string, unknown>[] = [
			{ type: "value", gridIndex: 0, position: "left", scale: true, alignTicks: true, axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { type: "dashed" } }, name: "%", nameLocation: "end", nameTextStyle: { fontSize: 10, padding: [0, 30, 0, 0] } },
			{ type: "value", gridIndex: 0, position: "right", scale: true, alignTicks: true, axisLabel: { fontSize: 10 }, splitLine: { show: false }, name: "abs", nameLocation: "end", nameTextStyle: { fontSize: 10, padding: [0, 0, 0, 30] } },
		];

		if (hasSubchart) {
			grids.push({ left: 60, right: 60, top: subGridTop, bottom: "5%", containLabel: false });
			xAxes.push({ type: "time", gridIndex: 1, axisLabel: { fontSize: 9 }, axisTick: { show: false } });
			yAxes.push({ type: "value", gridIndex: 1, scale: true, axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { type: "dashed" } } });
		}

		const echartsSeriesList: Record<string, unknown>[] = [];

		for (const s of mainSeries) {
			echartsSeriesList.push({
				name: s.name,
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: s.yAxisIndex ?? 0,
				data: s.data,
				step: stepForFreq(s.frequency),
				connectNulls: false,
				showSymbol: false,
				smooth: false,
				lineStyle: {
					width: 2.5,
					type: s.lineStyle ?? "solid",
				},
				endLabel: {
					show: true,
					formatter: "{a}",
					fontSize: 11,
					fontWeight: 600,
					distance: 8,
				},
				labelLayout: { moveOverlap: "shiftY" },
				emphasis: { focus: "series" },
				animationDuration: 2000,
				animationEasing: "cubicInOut",
				...(s.color ? { itemStyle: { color: s.color }, lineStyle: { color: s.color, width: 2.5, type: s.lineStyle ?? "solid" } } : {}),
			});
		}

		for (const s of subSeries) {
			echartsSeriesList.push({
				name: s.name,
				type: "bar",
				xAxisIndex: 1,
				yAxisIndex: 2,
				data: s.data,
				barMaxWidth: 8,
				...(s.color ? { itemStyle: { color: s.color } } : {}),
			});
		}

		const axisPointerLink = hasSubchart ? [{ xAxisIndex: "all" }] : [{ xAxisIndex: [0] }];

		const dataZoomEntries: Record<string, unknown>[] = [
			{ type: "slider", xAxisIndex: hasSubchart ? [0, 1] : [0], bottom: hasSubchart ? "18%" : "3%", height: 20, filterMode: "weakFilter", borderColor: "transparent", fillerColor: "rgba(59,130,246,0.12)", start: zoomStart, end: zoomEnd },
			{ type: "inside", xAxisIndex: hasSubchart ? [0, 1] : [0], filterMode: "weakFilter", start: zoomStart, end: zoomEnd },
		];

		return {
			animation: true,
			animationDuration: 2000,
			animationEasing: "cubicInOut" as const,
			backgroundColor: "transparent",
			textStyle: { fontFamily: "Inter, system-ui, sans-serif", fontSize: 12 },
			grid: grids,
			xAxis: xAxes,
			yAxis: yAxes,
			series: echartsSeriesList,
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "cross", link: axisPointerLink },
				confine: true,
				formatter: (params: any) => {
					if (!Array.isArray(params) || params.length === 0) return "";
					const date = params[0].axisValueLabel;
					let html = `<div style="font-weight:600;margin-bottom:4px">${date}</div>`;
					for (const p of params) {
						const val = typeof p.value === "number" ? p.value : Array.isArray(p.value) ? p.value[1] : p.value;
						html += `<div style="display:flex;gap:8px;align-items:center">
							<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>
							<span>${p.seriesName}</span>
							<span style="font-weight:600;margin-left:auto">${formatNumber(val as number, 2)}</span>
						</div>`;
					}
					return html;
				},
			},
			legend: {
				type: "scroll",
				top: 4,
				left: 60,
				right: 60,
				textStyle: { fontSize: 11 },
			},
			toolbox: {
				show: true,
				right: 8,
				top: 4,
				feature: {
					saveAsImage: { show: true, name: "netz-macro-chart" },
					restore: { show: true },
				},
			},
			axisPointer: { link: axisPointerLink },
			dataZoom: dataZoomEntries,
		} as Record<string, unknown>;
	});

	let zoomStart = $state(0);
	let zoomEnd = $state(100);

	function applyTimeRange(range: typeof TIME_RANGES[number]) {
		onTimeRangeChange?.(range);
		// Compute zoom window as percentage of all data
		const allDates = series.flatMap((s) => s.data.map(([d]) => new Date(d).getTime()));
		if (allDates.length === 0) { zoomStart = 0; zoomEnd = 100; return; }
		const minTs = Math.min(...allDates);
		const maxTs = Math.max(...allDates);
		const span = maxTs - minTs;
		if (span <= 0) { zoomStart = 0; zoomEnd = 100; return; }

		const months = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "2Y": 24 } as const;
		const windowMs = (months[range] ?? 24) * 30.44 * 24 * 60 * 60 * 1000;
		const startTs = Math.max(maxTs - windowMs, minTs);
		zoomStart = ((startTs - minTs) / span) * 100;
		zoomEnd = 100;
	}
</script>

<div class="macro-chart-wrapper">
	<div class="macro-chart-toolbar">
		{#each TIME_RANGES as range (range)}
			<button
				class="range-btn"
				class:range-btn--active={timeRange === range}
				onclick={() => applyTimeRange(range)}
			>
				{range}
			</button>
		{/each}
	</div>

	{#if hasMixedFrequency && showMixedBanner}
		<div class="mixed-freq-banner">
			<span>Mixed frequencies — quarterly/annual series forward-filled to align with daily data</span>
			<button class="banner-dismiss" onclick={() => (showMixedBanner = false)}>&times;</button>
		</div>
	{/if}

	<ChartContainer
		{option}
		{height}
		loading={fetching && series.length === 0}
		empty={!fetching && series.length === 0}
		emptyMessage="Select indicators to display"
		ariaLabel="Macro Intelligence Chart"
		{...rest}
	/>
</div>

<style>
	.macro-chart-wrapper {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.macro-chart-toolbar {
		display: flex;
		gap: 2px;
		padding: 8px 16px;
		align-self: flex-end;
	}

	.range-btn {
		padding: 4px 10px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-secondary);
		cursor: pointer;
		transition: all 150ms ease;
	}

	.range-btn:hover {
		background: var(--ii-surface-alt);
	}

	.range-btn--active {
		background: var(--ii-brand-primary);
		color: white;
		border-color: var(--ii-brand-primary);
	}

	.mixed-freq-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 6px 16px;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-secondary);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.banner-dismiss {
		border: none;
		background: none;
		color: var(--ii-text-muted);
		cursor: pointer;
		font-size: 16px;
		line-height: 1;
		padding: 0 4px;
	}
</style>

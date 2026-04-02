<!--
  Portfolio NAV Time-Series Chart — area line with daily return bars.
  Dual Y-axis: NAV (left) + Daily Return % (right).
  Supports base-100 normalization, time range selectors, view mode toggle, benchmark overlay.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions, echarts } from "@investintell/ui/charts/echarts-setup";
	import { formatPercent, formatNumber } from "@investintell/ui";
	import type { NAVPoint } from "$lib/types/model-portfolio";

	interface Props {
		navSeries: NAVPoint[];
		benchmarkSeries?: { date: string; nav: number }[] | null;
		inceptionDate?: string | null;
		height?: number;
		loading?: boolean;
		baseIndex?: number | null;
	}

	let {
		navSeries,
		benchmarkSeries = null,
		inceptionDate,
		height = 320,
		loading = false,
		baseIndex = 100,
	}: Props = $props();

	let isEmpty = $derived(!navSeries || navSeries.length === 0);

	// ── View mode & time range ────────────────────────────────────────────
	const TIME_RANGES = ["1M", "3M", "6M", "1Y", "YTD", "SI"] as const;
	type TimeRange = typeof TIME_RANGES[number];

	let viewMode = $state<"base100" | "absolute">("base100");
	let timeRange = $state<TimeRange>("SI");

	// ── Compute window start date ─────────────────────────────────────────
	function computeWindowStartIndex(series: NAVPoint[], range: TimeRange): number {
		if (range === "SI" || series.length === 0) return 0;
		const lastPoint = series[series.length - 1]!;
		const lastDate = new Date(lastPoint.date);
		let cutoff: Date;

		if (range === "YTD") {
			cutoff = new Date(lastDate.getFullYear(), 0, 1);
		} else {
			const months: Record<string, number> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 };
			cutoff = new Date(lastDate);
			cutoff.setMonth(cutoff.getMonth() - (months[range] ?? 12));
		}

		const cutoffStr = cutoff.toISOString().slice(0, 10);
		for (let i = 0; i < series.length; i++) {
			if (series[i]!.date >= cutoffStr) return i;
		}
		return 0;
	}

	let windowStartIdx = $derived(computeWindowStartIndex(navSeries, timeRange));
	let visibleSeries = $derived(navSeries.slice(windowStartIdx));

	// ── Base-100 normalization (keyed to visible window start) ────────────
	let displaySeries = $derived.by(() => {
		if (viewMode !== "base100" || !baseIndex || visibleSeries.length === 0) return visibleSeries;
		const firstPoint = visibleSeries[0]!;
		if (firstPoint.nav === 0) return visibleSeries;
		const base = firstPoint.nav;
		return visibleSeries.map(p => ({
			...p,
			nav: (p.nav / base) * baseIndex,
		}));
	});

	let displayBenchmark = $derived.by(() => {
		if (!benchmarkSeries || benchmarkSeries.length === 0) return null;
		const cutoffDate = visibleSeries.length > 0 ? visibleSeries[0]!.date : null;
		let filtered = cutoffDate
			? benchmarkSeries.filter(p => p.date >= cutoffDate)
			: benchmarkSeries;
		if (viewMode !== "base100" || !baseIndex || filtered.length === 0) return filtered;
		const firstBm = filtered[0]!;
		if (firstBm.nav === 0) return filtered;
		const base = firstBm.nav;
		return filtered.map(p => ({ ...p, nav: (p.nav / base) * baseIndex }));
	});

	// ── Cumulative return label ───────────────────────────────────────────
	let cumulativeReturn = $derived.by(() => {
		if (visibleSeries.length < 2) return null;
		const first = visibleSeries[0]!.nav;
		const last = visibleSeries[visibleSeries.length - 1]!.nav;
		if (first === 0) return null;
		return (last - first) / first;
	});

	// ── ECharts option ────────────────────────────────────────────────────
	let option = $derived.by(() => {
		if (isEmpty) return {};

		const navData = displaySeries.map((d) => [d.date, d.nav]);
		const returnData = displaySeries.map((d) => [d.date, d.daily_return != null ? d.daily_return * 100 : null]);

		const markLineData: Array<{ name: string; xAxis: string }> = [];
		if (inceptionDate && timeRange === "SI") {
			markLineData.push({ name: "Inception", xAxis: inceptionDate });
		}

		const seriesList: Record<string, unknown>[] = [
			{
				name: viewMode === "base100" && baseIndex ? `NAV (Base ${baseIndex})` : "NAV",
				type: "line",
				yAxisIndex: 0,
				data: navData,
				smooth: true,
				symbol: "none",
				sampling: "lttb",
				large: navData.length > 500,
				largeThreshold: 500,
				lineStyle: { width: 2 },
				areaStyle: {
					color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
						{ offset: 0, color: "rgba(27, 54, 93, 0.25)" },
						{ offset: 0.7, color: "rgba(27, 54, 93, 0.05)" },
						{ offset: 1, color: "rgba(27, 54, 93, 0)" },
					]),
				},
				markLine: markLineData.length > 0
					? {
						silent: true,
						symbol: "none",
						animation: false,
						lineStyle: { type: "dashed" as const, color: "#94a3b8", width: 1 },
						label: {
							show: true,
							position: "start" as const,
							formatter: "Inception",
							fontSize: 10,
							color: "#64748b",
							backgroundColor: "rgba(255,255,255,0.85)",
							padding: [2, 6],
							borderRadius: 3,
						},
						data: markLineData,
					}
					: undefined,
			},
			{
				name: "Daily Return",
				type: "bar",
				yAxisIndex: 1,
				data: returnData,
				barMaxWidth: 3,
				barMinWidth: 1,
				large: returnData.length > 500,
				largeThreshold: 500,
				itemStyle: {
					color(params: { value?: unknown[] }) {
						const val = Array.isArray(params.value) ? params.value[1] : 0;
						return Number(val) >= 0 ? "rgba(34, 197, 94, 0.45)" : "rgba(239, 68, 68, 0.45)";
					},
				},
				emphasis: { disabled: true },
			},
		];

		// Benchmark overlay
		if (displayBenchmark && displayBenchmark.length > 0) {
			seriesList.push({
				name: "Benchmark",
				type: "line",
				yAxisIndex: 0,
				data: displayBenchmark.map(d => [d.date, d.nav]),
				smooth: true,
				symbol: "none",
				sampling: "lttb",
				lineStyle: { width: 1.5, type: "dashed", color: "#94a3b8" },
				itemStyle: { color: "#94a3b8" },
			});
		}

		const yAxisName = viewMode === "base100" && baseIndex ? `Base ${baseIndex}` : "NAV";

		return {
			...globalChartOptions,
			grid: { left: 60, right: 60, top: 32, bottom: 50, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const first = list[0] as { axisValueLabel?: string };
					let html = `<strong>${first.axisValueLabel ?? ""}</strong>`;
					for (const p of list as Array<{ seriesName?: string; value?: unknown[]; marker?: string }>) {
						const val = Array.isArray(p.value) ? p.value[1] : p.value;
						if (val == null) continue;
						const formatted = p.seriesName === "Daily Return"
							? formatPercent(Number(val) / 100)
							: formatNumber(Number(val), viewMode === "base100" ? 2 : 4);
						html += `<br/>${p.marker ?? ""} ${p.seriesName}: ${formatted}`;
					}
					return html;
				},
			},
			xAxis: {
				type: "time" as const,
				boundaryGap: false,
				axisLabel: { fontSize: 10 },
			},
			yAxis: [
				{
					type: "value" as const,
					name: yAxisName,
					position: "left" as const,
					scale: true,
					alignTicks: true,
				},
				{
					type: "value" as const,
					name: "Daily Return",
					position: "right" as const,
					scale: true,
					splitLine: { show: false },
					axisLabel: { formatter: "{value}%" },
				},
			],
			dataZoom: [
				{ type: "inside" as const, xAxisIndex: 0, filterMode: "weakFilter" as const },
				{
					type: "slider" as const, xAxisIndex: 0, height: 24, bottom: 10,
					filterMode: "weakFilter" as const,
					borderColor: "transparent", fillerColor: "rgba(99, 102, 241, 0.12)",
				},
			],
			series: seriesList,
			legend: {
				show: true,
				bottom: 36,
				data: seriesList.map(s => s.name as string),
			},
		};
	});
</script>

{#if isEmpty && !loading}
	<div class="nav-empty">
		<p>No NAV data available — portfolio NAV is synthesized daily by the background worker.</p>
	</div>
{:else}
	<div class="nav-chart-wrapper">
		<div class="nav-toolbar">
			<div class="nav-view-toggle">
				<button
					class="toggle-btn"
					class:toggle-btn--active={viewMode === "base100"}
					onclick={() => (viewMode = "base100")}
				>Base 100</button>
				<button
					class="toggle-btn"
					class:toggle-btn--active={viewMode === "absolute"}
					onclick={() => (viewMode = "absolute")}
				>Absolute</button>
			</div>
			<div class="nav-range-selector">
				{#each TIME_RANGES as range (range)}
					<button
						class="range-btn"
						class:range-btn--active={timeRange === range}
						onclick={() => (timeRange = range)}
					>{range}</button>
				{/each}
			</div>
		</div>

		{#if cumulativeReturn !== null}
			<div class="nav-cumulative">
				<span class="cumulative-label">
					{timeRange === "SI" ? "Since Inception" : timeRange}:
				</span>
				<span
					class="cumulative-value"
					class:cumulative-positive={cumulativeReturn >= 0}
					class:cumulative-negative={cumulativeReturn < 0}
				>
					{cumulativeReturn >= 0 ? "+" : ""}{formatPercent(cumulativeReturn)}
				</span>
			</div>
		{/if}

		<ChartContainer
			{option}
			{height}
			{loading}
			empty={isEmpty}
			emptyMessage="No NAV data available"
			ariaLabel="Portfolio NAV time-series chart"
		/>
	</div>
{/if}

<style>
	.nav-empty {
		padding: 32px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.nav-chart-wrapper {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.nav-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 16px;
		gap: 12px;
	}

	.nav-view-toggle {
		display: flex;
		gap: 1px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		overflow: hidden;
	}

	.toggle-btn {
		padding: 4px 10px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		border: none;
		background: var(--ii-surface-elevated);
		color: var(--ii-text-secondary);
		cursor: pointer;
		transition: all 150ms ease;
	}

	.toggle-btn:hover {
		background: var(--ii-surface-alt);
	}

	.toggle-btn--active {
		background: var(--ii-brand-primary);
		color: white;
	}

	.nav-range-selector {
		display: flex;
		gap: 2px;
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

	.nav-cumulative {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 16px 4px;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.cumulative-label {
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.cumulative-value {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.cumulative-positive {
		color: var(--ii-success);
	}

	.cumulative-negative {
		color: var(--ii-danger);
	}
</style>

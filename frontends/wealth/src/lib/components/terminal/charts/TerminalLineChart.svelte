<!--
	TerminalLineChart.svelte
	========================

	Reference pattern wrapper from Appendix A #1 (NAV time series).
	All other pattern wrappers (TerminalHeatmap, TerminalTreemap,
	TerminalDistribution, TerminalRollingBand, TerminalCandlestick,
	TerminalRadar) should follow this exact composition:

	  1. Accept a minimal, domain-shaped prop surface (time-series
	     tuples, labels, title) — never raw ECharts option objects.
	  2. Build an option via `createTerminalChartOptions()`.
	  3. Delegate rendering to <TerminalChart />.
	  4. Never import `echarts` directly.
	  5. Never write hex, inline duration literals, or Intl.* calls.

	Consumers:
	  - Live Workbench NAV strip
	  - Builder preview
	  - Focus Mode fund hero chart
	  - Screener sparkline grid (via a thin sparkline variant)
-->
<script lang="ts">
	import { createTerminalChartOptions, type ChoreoSlot } from "@investintell/ui";
	import type { EChartsOption } from "echarts";
	import TerminalChart from "./TerminalChart.svelte";

	/** One continuous series. */
	export interface TerminalLineSeries {
		name: string;
		/** Array of [ms-epoch, value] tuples. Monotonic time expected. */
		data: ReadonlyArray<readonly [number, number]>;
		/**
		 * 0-indexed color slot from the terminal dataviz palette. When
		 * omitted, ECharts assigns sequential colors from the factory.
		 */
		colorSlot?: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;
		/** Draw as smoothed area (NAV hero) rather than plain line. */
		area?: boolean;
	}

	interface Props {
		series: ReadonlyArray<TerminalLineSeries>;
		height?: number;
		/** Choreo slot for the reveal animation. Defaults to `primary`. */
		slot?: ChoreoSlot;
		/** Render backend. Heroes stay on canvas; tiny strips can use svg. */
		renderer?: "canvas" | "svg";
		/** Hide x-axis ticks/labels (use for ticker-strip mode). */
		compact?: boolean;
		/** Show legend (usually false — panel headers label the series). */
		showLegend?: boolean;
		ariaLabel?: string;
		empty?: boolean;
		loading?: boolean;
	}

	const {
		series,
		height = 320,
		slot = "primary",
		renderer = "canvas",
		compact = false,
		showLegend = false,
		ariaLabel = "Time series",
		empty = false,
		loading = false,
	}: Props = $props();

	const option = $derived<EChartsOption>(
		createTerminalChartOptions({
			slot,
			showXAxisLabels: !compact,
			showYAxisLabels: !compact,
			showLegend,
			series: series.map((s) => ({
				name: s.name,
				type: "line" as const,
				showSymbol: false,
				smooth: true,
				sampling: "lttb" as const,
				progressive: 2000,
				progressiveThreshold: 4000,
				lineStyle: { width: s.area ? 1.25 : 1.5 },
				areaStyle: s.area ? { opacity: 0.14 } : undefined,
				// ECharts wants mutable tuples; our prop surface is readonly.
				// The factory never mutates data — this cast is contract-safe.
				data: s.data.map((pt) => [pt[0], pt[1]] as [number, number]),
				...(s.colorSlot !== undefined ? { colorBy: "series" as const, seriesIndex: s.colorSlot } : {}),
			})),
		}),
	);
</script>

<TerminalChart
	{option}
	{renderer}
	{height}
	{ariaLabel}
	{empty}
	{loading}
	emptyMessage="NO SERIES"
/>

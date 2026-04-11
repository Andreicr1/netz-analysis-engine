// @investintell/ui — Chart Components (ECharts)
// ======================================

export { default as ChartContainer } from "./ChartContainer.svelte";
export { default as TimeSeriesChart } from "./TimeSeriesChart.svelte";
export { default as RegimeChart } from "./RegimeChart.svelte";
export { default as GaugeChart } from "./GaugeChart.svelte";
export { default as BarChart } from "./BarChart.svelte";
export { default as FunnelChart } from "./FunnelChart.svelte";
export { default as HeatmapChart } from "./HeatmapChart.svelte";
export { default as CorrelationHeatmap } from "./CorrelationHeatmap.svelte";
export { default as ScatterChart } from "./ScatterChart.svelte";

export type { BaseChartProps } from "./ChartContainer.svelte";

// ── Terminal primitives (Wealth OS brutalist surface) ──────
// Motion grammar: one shared timing system for every (terminal)/
// Svelte transition and every ECharts animationDelay.
export {
	choreo,
	terminalDuration,
	terminalEasing,
	terminalBezier,
	animationDelayForSlot,
	delayFor,
	durationFor,
	prefersReducedMotion,
	svelteTransitionFor,
} from "./choreo.js";
export type {
	ChoreoSlot,
	TerminalDurationName,
	MotionSlot,
	MotionDuration,
	SvelteTransitionOptions,
} from "./choreo.js";

// Terminal chart factory: single source of aesthetic truth for
// every chart rendered inside frontends/wealth/src/routes/(terminal).
export { createTerminalChartOptions, readTerminalTokens } from "./terminal-options.js";
export type {
	TerminalChartOptionsInput,
	TerminalChartTokens,
} from "./terminal-options.js";

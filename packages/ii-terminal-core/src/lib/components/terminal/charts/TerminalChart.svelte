<!--
	TerminalChart.svelte
	====================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md §1.2, §1.4, Appendix G

	The only terminal Svelte component allowed to import ECharts directly.
	Every pattern wrapper composes `TerminalChart` under the hood. ESLint
	enforces this via `no-restricted-imports`.

	Responsibilities:
	  - Lifecycle: `echarts.init` on mount, `dispose` on destroy.
	  - ResizeObserver for fluid panels (LayoutCage is fixed but
	    split panes and focus mode resize dynamically).
	  - Rebinds `setOption` on reactive `option` updates.
	  - Exposes the `echarts` instance via `bindable` so pattern
	    wrappers can call `setOption({ replaceMerge })` for live
	    streams without paying the cost of a full notMerge.
	  - Renderer selection (canvas/svg) is controlled by the
	    caller so heatmaps/scatter stay on canvas and small
	    sparklines stay on svg.

	This wrapper never bakes aesthetic decisions. Callers build
	option objects through `createTerminalChartOptions()` from
	@investintell/ui and pass them down.
-->
<script lang="ts">
	import { onMount } from "svelte";
	// TerminalChart is the single authorized direct consumer of
	// the `echarts` module inside the wealth frontend.
	import * as echarts from "echarts/core";
	import {
		LineChart,
		BarChart,
		ScatterChart,
		HeatmapChart,
		TreemapChart,
		CandlestickChart,
		RadarChart,
		CustomChart,
	} from "echarts/charts";
	import {
		GridComponent,
		TooltipComponent,
		LegendComponent,
		DataZoomComponent,
		VisualMapComponent,
		MarkLineComponent,
		MarkAreaComponent,
		MarkPointComponent,
		DatasetComponent,
		TransformComponent,
	} from "echarts/components";
	import { CanvasRenderer, SVGRenderer } from "echarts/renderers";
	import type { EChartsOption } from "echarts";

	echarts.use([
		LineChart,
		BarChart,
		ScatterChart,
		HeatmapChart,
		TreemapChart,
		CandlestickChart,
		RadarChart,
		CustomChart,
		GridComponent,
		TooltipComponent,
		LegendComponent,
		DataZoomComponent,
		VisualMapComponent,
		MarkLineComponent,
		MarkAreaComponent,
		MarkPointComponent,
		DatasetComponent,
		TransformComponent,
		CanvasRenderer,
		SVGRenderer,
	]);

	interface Props {
		/** Full ECharts option object — normally built via createTerminalChartOptions. */
		option: EChartsOption;
		/** Render backend: canvas (heroes, heatmaps) or svg (sparklines, radar). */
		renderer?: "canvas" | "svg";
		/** Height in pixels. Width is 100% of the parent container. */
		height?: number;
		/** ARIA label for assistive tech (charts are rendered on canvas). */
		ariaLabel?: string;
		/** Empty state toggle. When true, hides the chart and shows an ASCII placeholder. */
		empty?: boolean;
		emptyMessage?: string;
		/** Loading toggle. Terminal-native CSS hatching — no spinner. */
		loading?: boolean;
		/** Bindable ECharts instance (for live setOption calls from pattern wrappers). */
		instance?: echarts.ECharts | undefined;
	}

	let {
		option,
		renderer = "canvas",
		height = 320,
		ariaLabel = "Terminal chart",
		empty = false,
		emptyMessage = "NO DATA",
		loading = false,
		instance = $bindable(),
	}: Props = $props();

	let hostEl: HTMLDivElement | undefined = $state();

	/*
	 * ============================================================
	 * DO NOT CONVERT `lastOption` TO `$state` — REACTIVITY TRAP
	 * ============================================================
	 *
	 * `lastOption` is a PLAIN module-local variable on purpose. It
	 * exists ONLY to short-circuit the `$effect` below when the
	 * caller passes the same option reference twice.
	 *
	 * IF YOU WRAP THIS IN `$state`, THE FOLLOWING HAPPENS:
	 *
	 *   1. `$state` deeply proxies the EChartsOption object.
	 *   2. The proxy is no longer reference-equal to the raw
	 *      `option` prop the caller passed in (`option === lastOption`
	 *      becomes permanently false).
	 *   3. The `$effect` re-reads `lastOption` on every assignment,
	 *      establishes a reactive dependency on it, and rebinds the
	 *      ECharts instance via `setOption` on EVERY tick.
	 *   4. ECharts triggers an internal redraw, which mutates the
	 *      bound `instance` prop (`$bindable`), which re-runs the
	 *      effect → INFINITE LOOP, browser tab freezes.
	 *
	 * This pattern is load-bearing for the entire `(terminal)/`
	 * chart pipeline. The Phase 1 audit (2026-04-11) flagged it as
	 * the #1 risk for future refactors. Leave it as a plain `let`.
	 * ============================================================
	 */
	let lastOption: EChartsOption | null = null;

	onMount(() => {
		if (!hostEl) return;
		instance = echarts.init(hostEl, null, { renderer });
		const ro = new ResizeObserver(() => instance?.resize());
		ro.observe(hostEl);
		return () => {
			ro.disconnect();
			instance?.dispose();
			instance = undefined;
		};
	});

	$effect(() => {
		if (!instance || empty || loading) return;
		if (option === lastOption) return;
		lastOption = option;
		instance.setOption(option, { notMerge: true });
	});
</script>

<div class="terminal-chart" style:height="{height}px">
	{#if loading}
		<div class="terminal-chart__state terminal-chart__state--loading" aria-hidden="true">
			<span class="terminal-chart__state-label">█ LOADING</span>
		</div>
	{/if}

	{#if empty && !loading}
		<div class="terminal-chart__state terminal-chart__state--empty" aria-hidden="true">
			<span class="terminal-chart__state-label">[ {emptyMessage} ]</span>
		</div>
	{/if}

	<div
		bind:this={hostEl}
		class="terminal-chart__host"
		role="img"
		aria-label={ariaLabel}
		style:visibility={empty || loading ? "hidden" : "visible"}
	></div>
</div>

<style>
	.terminal-chart {
		position: relative;
		width: 100%;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
	}

	.terminal-chart__host {
		width: 100%;
		height: 100%;
	}

	.terminal-chart__state {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: var(--terminal-z-panel);
		background: var(--terminal-bg-panel);
		color: var(--terminal-fg-tertiary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.terminal-chart__state--loading {
		background-image: repeating-linear-gradient(
			45deg,
			transparent 0 6px,
			var(--terminal-bg-panel-raised) 6px 8px
		);
	}

	.terminal-chart__state-label {
		padding: var(--terminal-space-2) var(--terminal-space-4);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
	}
</style>

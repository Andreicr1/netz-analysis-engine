<!--
  WorkbenchCoreChart — Phase 9 Block C central chart of the Live
  Workbench. Terminal-dark styled ECharts line chart that slides
  smoothly as ticks arrive from the LivePricePoller.

  Design rules (per original plan DL9 + the re-scoped Block C
  mandate):
    - ONE ECharts instance, initialised once in onMount. Never
      destroyed on tick updates. Never re-mounted via {#if}.
    - Updates via ``setOption(patch, { notMerge: false,
      lazyUpdate: true, replaceMerge: ['series'] })`` — the
      "slide-in" pattern. Avoids the notMerge churn that
      ChartContainer does for static option swaps.
    - Base theme is "Terminal Dark": transparent background,
      hairline dashed split lines on the y axis only, no x split
      lines, monochrome numeric axis labels, 1.5px brand-accent
      line with a soft gradient fill beneath. No animation.
    - Reads the brand accent from the live CSS custom property
      on mount + on theme changes (same pattern as
      MainPortfolioChart) so a future light-mode toggle recolours
      the line without a rebuild.

  Contract:
    ticks  — the full sliding buffer from LivePricePoller. The
             chart renders the entire series on every tick — the
             replaceMerge pattern means ECharts only diffs the
             series data, not the axes / grid / legend.
    height — pixel height of the chart canvas (default 260).

  Cleanup:
    The onMount return disposes the chart instance and disconnects
    the ResizeObserver. The parent shell's $effect manages the
    poller lifecycle; this component only cares about the ticks
    prop and never touches the poller directly.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { echarts } from "@investintell/ui/charts/echarts-setup";
	import { formatNumber } from "@investintell/ui";
	import type { PriceTick } from "../../../../workers/live_price_poll.svelte";

	interface Props {
		ticks: readonly PriceTick[];
		height?: number;
		ariaLabel?: string;
	}

	let {
		ticks,
		height = 260,
		ariaLabel = "Live price chart",
	}: Props = $props();

	let containerEl: HTMLDivElement | undefined = $state();
	let chart: ReturnType<typeof echarts.init> | null = null;

	// Resolve brand accent from the live computed style so the chart
	// recolours cleanly on theme changes. Matches MainPortfolioChart.
	let brandAccent = $state("#2d7ef7");

	function readBrandAccent(): string {
		if (typeof document === "undefined") return "#2d7ef7";
		const style = getComputedStyle(document.documentElement);
		return (
			style.getPropertyValue("--ii-brand-accent").trim() ||
			style.getPropertyValue("--ii-brand-primary").trim() ||
			"#2d7ef7"
		);
	}

	const seriesData = $derived(
		ticks.map((t) => [t.ts, Math.round(t.price * 10000) / 10000] as [number, number]),
	);

	function buildBaseOption(accent: string) {
		return {
			backgroundColor: "transparent",
			animation: false,
			textStyle: {
				fontFamily: "Urbanist, system-ui, sans-serif",
				color: "#85a0bd",
			},
			grid: {
				left: 56,
				right: 20,
				top: 18,
				bottom: 28,
				containLabel: false,
			},
			tooltip: {
				trigger: "axis" as const,
				backgroundColor: "rgba(20, 21, 25, 0.96)",
				borderColor: "rgba(64, 66, 73, 0.6)",
				borderWidth: 1,
				padding: [6, 10],
				textStyle: {
					color: "#ffffff",
					fontSize: 11,
					fontFamily: "Urbanist, system-ui, sans-serif",
				},
				axisPointer: {
					type: "line" as const,
					lineStyle: {
						color: "rgba(133, 160, 189, 0.4)",
						type: "dashed" as const,
					},
				},
				formatter(params: unknown) {
					const p = Array.isArray(params) ? params[0] : params;
					const v = (p as { value?: unknown }).value;
					if (!Array.isArray(v) || v.length < 2) return "";
					const ts = Number(v[0]);
					const price = Number(v[1]);
					const d = new Date(ts);
					const hh = d.getHours().toString().padStart(2, "0");
					const mm = d.getMinutes().toString().padStart(2, "0");
					const ss = d.getSeconds().toString().padStart(2, "0");
					return `<strong>${hh}:${mm}:${ss}</strong><br/>${formatNumber(price, 4)}`;
				},
			},
			xAxis: {
				type: "time" as const,
				boundaryGap: false,
				axisLine: { lineStyle: { color: "rgba(64, 66, 73, 0.6)" } },
				axisTick: { show: false },
				axisLabel: {
					color: "#85a0bd",
					fontSize: 9,
					fontFamily: "Urbanist, system-ui, sans-serif",
					hideOverlap: true,
				},
				splitLine: { show: false },
			},
			yAxis: {
				type: "value" as const,
				scale: true,
				axisLine: { show: false },
				axisTick: { show: false },
				axisLabel: {
					color: "#85a0bd",
					fontSize: 9,
					fontFamily: "Urbanist, system-ui, sans-serif",
					formatter: (value: number) => formatNumber(value, 3),
				},
				splitLine: {
					show: true,
					lineStyle: {
						color: "rgba(64, 66, 73, 0.4)",
						type: "dashed" as const,
					},
				},
			},
			series: [
				{
					id: "price",
					name: "Price",
					type: "line" as const,
					showSymbol: false,
					smooth: 0.2,
					lineStyle: { width: 1.5, color: accent },
					itemStyle: { color: accent },
					areaStyle: {
						color: {
							type: "linear" as const,
							x: 0,
							y: 0,
							x2: 0,
							y2: 1,
							colorStops: [
								{ offset: 0, color: "rgba(45, 126, 247, 0.28)" },
								{ offset: 1, color: "rgba(45, 126, 247, 0.02)" },
							],
						},
					},
					data: [] as Array<[number, number]>,
				},
			],
		};
	}

	onMount(() => {
		if (!containerEl) return;
		brandAccent = readBrandAccent();
		chart = echarts.init(containerEl, null, { renderer: "canvas" });
		chart.setOption(buildBaseOption(brandAccent), { notMerge: true });

		const ro = new ResizeObserver(() => chart?.resize());
		ro.observe(containerEl);

		// Recolour on theme change. Rebuilds the base option once per
		// flip — negligible cost compared to per-tick patches.
		const themeObserver = new MutationObserver(() => {
			brandAccent = readBrandAccent();
			if (chart) {
				chart.setOption(buildBaseOption(brandAccent), { notMerge: true });
			}
		});
		themeObserver.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ["data-theme"],
		});

		return () => {
			ro.disconnect();
			themeObserver.disconnect();
			chart?.dispose();
			chart = null;
		};
	});

	// Slide-in update path. Running through replaceMerge:['series']
	// means ECharts only diffs the series data array, leaving axes,
	// grid, tooltip, and markLines untouched between ticks.
	$effect(() => {
		if (!chart) return;
		const data = seriesData; // reactivity dependency pickup
		chart.setOption(
			{ series: [{ id: "price", data }] },
			{ notMerge: false, lazyUpdate: true, replaceMerge: ["series"] },
		);
	});
</script>

<div class="wcc-root" style:height="{height}px">
	<div
		bind:this={containerEl}
		class="wcc-canvas"
		role="img"
		aria-label={ariaLabel}
	></div>
</div>

<style>
	.wcc-root {
		position: relative;
		width: 100%;
		background: linear-gradient(
			180deg,
			rgba(20, 21, 25, 0.5) 0%,
			rgba(14, 15, 19, 0) 100%
		);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		padding: 12px;
		flex-shrink: 0;
		min-width: 0;
	}
	.wcc-canvas {
		width: 100%;
		height: 100%;
	}
</style>

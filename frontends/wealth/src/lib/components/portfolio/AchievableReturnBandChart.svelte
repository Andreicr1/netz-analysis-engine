<!--
  AchievableReturnBandChart — PR-A13 presentational chart that shows the
  two-point achievable return band (lower / upper) produced by the RU CVaR
  cascade (PR-A12). The vertical dashed marker sits at the operator's
  current CVaR limit; the shaded x-axis area (0 → min_achievable_cvar)
  marks the universe's infeasible region.

  Institutional UX discipline:
    - No inline hex literals; colours resolved from @netz/ui CSS
      custom properties via getComputedStyle (ECharts cannot parse
      var(--…)).
    - Fixed pixel height — Layout Cage pattern (feedback_layout_cage_pattern.md).
      Parent must not rely on ``height: 100%``.
    - Empty-band fallback renders a placeholder div at the same height so
      the panel doesn't reflow when a band is not yet available.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { formatPercent } from "@investintell/ui";
	import GenericEChart from "$wealth/components/charts/GenericEChart.svelte";
	import type { AchievableReturnBand } from "$wealth/types/cascade-telemetry";

	interface Props {
		band: AchievableReturnBand | null;
		cvarLimit: number;
		minAchievableCvar: number | null;
		height?: number;
	}

	let { band, cvarLimit, minAchievableCvar, height = 220 }: Props = $props();

	// Resolve tokens once on mount — ECharts options must receive concrete
	// colour strings. Re-reading on every $derived would bust the cache.
	let tokens = $state({ primary: "", warning: "", border: "", muted: "" });

	onMount(() => {
		const cs = getComputedStyle(document.documentElement);
		tokens = {
			primary: cs.getPropertyValue("--terminal-accent-amber").trim() || "#d19a2f",
			warning: cs.getPropertyValue("--terminal-status-warning").trim() || "#c29840",
			border: cs.getPropertyValue("--terminal-fg-muted").trim() || "#888888",
			muted: cs.getPropertyValue("--terminal-fg-secondary").trim() || "#b8b8b8",
		};
	});

	const chartOptions = $derived.by(() => {
		if (!band) return null;
		const series: unknown[] = [
			{
				type: "line",
				name: "Achievable band",
				showSymbol: true,
				symbolSize: 10,
				data: [
					[band.lower_at_cvar, band.lower],
					[band.upper_at_cvar, band.upper],
				],
				lineStyle: { color: tokens.primary, width: 2 },
				itemStyle: { color: tokens.primary },
			},
			{
				type: "line",
				data: [],
				markLine: {
					symbol: "none",
					silent: true,
					lineStyle: { color: tokens.warning, type: "dashed", width: 1 },
					label: {
						formatter: formatPercent(cvarLimit, 2),
						color: tokens.warning,
					},
					data: [{ xAxis: cvarLimit }],
				},
			},
		];
		if (minAchievableCvar !== null && minAchievableCvar > 0) {
			series.push({
				type: "line",
				data: [],
				markArea: {
					silent: true,
					itemStyle: { color: tokens.border, opacity: 0.12 },
					data: [[{ xAxis: 0 }, { xAxis: minAchievableCvar }]],
				},
			});
		}
		return {
			grid: { left: 56, right: 16, top: 16, bottom: 36, containLabel: true },
			xAxis: {
				type: "value",
				name: "Tail loss (95% CVaR)",
				nameLocation: "middle",
				nameGap: 24,
				nameTextStyle: { color: tokens.muted, fontSize: 11 },
				axisLabel: {
					formatter: (v: number) => formatPercent(v, 1),
					color: tokens.muted,
					fontSize: 10,
				},
				axisLine: { lineStyle: { color: tokens.border } },
				splitLine: { show: false },
			},
			yAxis: {
				type: "value",
				name: "Expected return",
				nameTextStyle: { color: tokens.muted, fontSize: 11 },
				axisLabel: {
					formatter: (v: number) => formatPercent(v, 1),
					color: tokens.muted,
					fontSize: 10,
				},
				axisLine: { lineStyle: { color: tokens.border } },
				splitLine: { lineStyle: { color: tokens.border, opacity: 0.25 } },
			},
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "cross" },
				formatter: (params: unknown) => {
					const arr = params as Array<{ value: [number, number] }>;
					const first = arr?.[0];
					if (!first) return "";
					const [x, y] = first.value;
					return `Tail loss ${formatPercent(x, 2)}<br/>Return ${formatPercent(y, 2)}`;
				},
			},
			series,
		};
	});
</script>

<div class="arbc-root" style:height="{height}px">
	{#if band && chartOptions}
		<GenericEChart options={chartOptions} {height} />
	{:else}
		<div class="arbc-empty" role="status">
			<p class="arbc-empty__msg">Run a construction to see the achievable return band.</p>
		</div>
	{/if}
</div>

<style>
	.arbc-root {
		width: 100%;
	}
	.arbc-empty {
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px dashed var(--terminal-fg-muted);
		background: var(--terminal-bg-panel);
	}
	.arbc-empty__msg {
		margin: 0;
		font-size: 12px;
		color: var(--terminal-fg-muted);
		font-family: var(--terminal-font-mono);
	}
</style>

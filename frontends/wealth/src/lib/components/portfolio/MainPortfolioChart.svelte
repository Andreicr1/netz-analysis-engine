<!--
  MainPortfolioChart — Backtest equity curve for the selected model portfolio.
  Displays real synthesized NAV data from the backend track-record endpoint.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions, echarts } from "@investintell/ui/charts/echarts-setup";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	let wrapEl: HTMLDivElement | undefined = $state();
	let chartHeight = $state(0);

	onMount(() => {
		if (!wrapEl) return;
		const ro = new ResizeObserver(([entry]) => {
			chartHeight = Math.floor(entry!.contentRect.height);
		});
		ro.observe(wrapEl);
		// Initial measurement
		chartHeight = wrapEl.clientHeight;
		return () => ro.disconnect();
	});

	let navData = $derived(workspace.navSeries);
	let isEmpty = $derived(navData.length === 0);
	let isLoading = $derived(workspace.isLoadingTrackRecord);

	let option = $derived.by(() => {
		if (isEmpty) return {};

		const seriesData = navData.map((d) => [d.date, d.nav]);
		const firstNav = navData[0]?.nav ?? 1000;
		const lastNav = navData[navData.length - 1]?.nav ?? 1000;
		const totalReturn = ((lastNav - firstNav) / firstNav) * 100;

		return {
			...globalChartOptions,
			grid: { left: 56, right: 24, top: 28, bottom: 48, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				formatter(params: unknown) {
					const p = Array.isArray(params) ? params[0] : params;
					const { axisValueLabel, value } = p as { axisValueLabel?: string; value?: unknown[] };
					const nav = Array.isArray(value) ? value[1] : null;
					if (nav == null) return "";
					return `<strong>${axisValueLabel ?? ""}</strong><br/>NAV: ${Number(nav).toFixed(2)}`;
				},
			},
			xAxis: {
				type: "time" as const,
				boundaryGap: false,
				axisLabel: { fontSize: 10 },
			},
			yAxis: {
				type: "value" as const,
				name: "NAV",
				scale: true,
				splitLine: { lineStyle: { type: "dashed" as const } },
			},
			dataZoom: [
				{ type: "inside" as const, xAxisIndex: 0, filterMode: "weakFilter" as const },
				{
					type: "slider" as const, xAxisIndex: 0, height: 20, bottom: 6,
					filterMode: "weakFilter" as const,
					borderColor: "transparent",
					fillerColor: "rgba(1, 119, 251, 0.12)",
				},
			],
			series: [
				{
					name: "Portfolio NAV",
					type: "line" as const,
					data: seriesData,
					smooth: true,
					symbol: "none",
					sampling: "lttb",
					lineStyle: { width: 2, color: "#0177fb" },
					itemStyle: { color: "#0177fb" },
					areaStyle: {
						color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
							{ offset: 0, color: "rgba(1, 119, 251, 0.18)" },
							{ offset: 0.6, color: "rgba(1, 119, 251, 0.04)" },
							{ offset: 1, color: "rgba(1, 119, 251, 0)" },
						]),
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ yAxis: firstNav }],
						lineStyle: { color: "var(--ii-text-muted)", type: "dashed" as const, width: 1 },
						label: {
							position: "insideEndTop" as const,
							formatter: `Base ${firstNav.toFixed(0)}`,
							fontSize: 10,
						},
					},
				},
			],
			graphic: [
				{
					type: "text" as const,
					right: 16,
					top: 6,
					style: {
						text: `${totalReturn >= 0 ? "+" : ""}${totalReturn.toFixed(2)}%`,
						fontSize: 13,
						fontWeight: 700 as const,
						fill: totalReturn >= 0 ? "var(--ii-success)" : "var(--ii-danger)",
						fontFamily: "Urbanist, system-ui, sans-serif",
					},
				},
			],
		};
	});
</script>

{#if workspace.portfolio}
	<div class="main-chart-wrap" bind:this={wrapEl}>
		{#if chartHeight > 0}
			<ChartContainer
				{option}
				height={chartHeight}
				empty={isEmpty && !isLoading}
				emptyMessage="No track-record data available"
				loading={isLoading}
				ariaLabel="Portfolio backtest equity curve"
			/>
		{/if}
	</div>
{:else}
	<div class="main-chart-empty">
		<span>Select a portfolio to view the backtest chart</span>
	</div>
{/if}

<style>
	.main-chart-wrap {
		flex: 1;
		min-height: 0;
	}

	.main-chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>

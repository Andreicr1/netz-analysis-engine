<!--
  MainPortfolioChart — Backtest equity curve for the selected model portfolio.
  Displays real synthesized NAV data from the backend track-record endpoint.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { formatNumber, formatPercent } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	let wrapEl: HTMLDivElement | undefined = $state();
	let chartHeight = $state(0);

	// ECharts series colors must be resolved hex/rgba (CSS vars don't work
	// inside ECharts option). Read the brand-primary token from the live
	// computed style at mount and re-read on theme changes.
	let brandPrimary = $state("#0177fb"); // fallback if document is unavailable
	let brandPrimaryFill = $derived(`color-mix(in srgb, ${brandPrimary} 12%, transparent)`);

	function readBrandPrimary(): string {
		if (typeof document === "undefined") return "#0177fb";
		return getComputedStyle(document.documentElement)
			.getPropertyValue("--ii-brand-primary").trim() || "#0177fb";
	}

	onMount(() => {
		if (!wrapEl) return;
		brandPrimary = readBrandPrimary();
		const ro = new ResizeObserver(([entry]) => {
			chartHeight = Math.floor(entry!.contentRect.height);
		});
		ro.observe(wrapEl);
		// Initial measurement
		chartHeight = wrapEl.clientHeight;
		// Re-resolve token on theme change
		const themeObserver = new MutationObserver(() => { brandPrimary = readBrandPrimary(); });
		themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
		return () => { ro.disconnect(); themeObserver.disconnect(); };
	});

	let navData = $derived(workspace.navSeries);
	let isEmpty = $derived(navData.length === 0);
	let isLoading = $derived(workspace.isLoadingTrackRecord);

	let option = $derived.by(() => {
		if (isEmpty) return {};

		const seriesData = navData.map((d) => [d.date, d.nav]);
		const firstNav = navData[0]?.nav ?? 1000;
		const lastNav = navData[navData.length - 1]?.nav ?? 1000;
		const totalReturn = (lastNav - firstNav) / firstNav;

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
					return `<strong>${axisValueLabel ?? ""}</strong><br/>NAV: ${formatNumber(Number(nav), 2)}`;
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
					fillerColor: brandPrimaryFill,
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
					// Institutional line chart — no area fill / gradient.
					lineStyle: { width: 2, color: brandPrimary },
					itemStyle: { color: brandPrimary },
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ yAxis: firstNav }],
						lineStyle: { color: "var(--ii-text-muted)", type: "dashed" as const, width: 1 },
						label: {
							position: "insideEndTop" as const,
							formatter: `Base ${formatNumber(firstNav, 0)}`,
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
						text: `${totalReturn >= 0 ? "+" : ""}${formatPercent(totalReturn, 2)}`,
						fontSize: 13,
						fontWeight: 700 as const,
						fill: totalReturn >= 0 ? "var(--ii-success)" : "var(--ii-danger)",
					},
				},
			],
		};
	});
</script>

{#if workspace.portfolio}
	<div class="main-chart-wrap" bind:this={wrapEl}>
		{#if isLoading}
			<div class="main-chart-placeholder">
				<div class="main-chart-spinner"></div>
				<span>Loading track record...</span>
			</div>
		{:else if isEmpty}
			<div class="main-chart-placeholder">
				<span class="main-chart-placeholder-title">No track-record data</span>
				<span>The NAV synthesizer has not generated data for this portfolio yet.</span>
			</div>
		{:else if chartHeight > 0}
			<ChartContainer
				{option}
				height={chartHeight}
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
		height: 100%;
	}

	.main-chart-empty,
	.main-chart-placeholder {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 6px;
		flex: 1;
		height: 100%;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.main-chart-placeholder-title {
		font-size: var(--ii-text-body, 0.875rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.main-chart-spinner {
		width: 24px;
		height: 24px;
		border: 3px solid color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
		border-top-color: var(--ii-brand-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>

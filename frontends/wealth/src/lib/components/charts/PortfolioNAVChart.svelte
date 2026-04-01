<!--
  Portfolio NAV Time-Series Chart — area line with daily return bars.
  Dual Y-axis: NAV (left) + Daily Return % (right).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions, echarts } from "@investintell/ui/charts/echarts-setup";
	import { formatPercent, formatNumber } from "@investintell/ui";
	import type { NAVPoint } from "$lib/types/model-portfolio";

	interface Props {
		navSeries: NAVPoint[];
		inceptionDate?: string | null;
		height?: number;
		loading?: boolean;
	}

	let { navSeries, inceptionDate, height = 320, loading = false }: Props = $props();

	let isEmpty = $derived(!navSeries || navSeries.length === 0);

	let option = $derived.by(() => {
		if (isEmpty) return {};

		const navData = navSeries.map((d) => [d.date, d.nav]);
		const returnData = navSeries.map((d) => [d.date, d.daily_return != null ? d.daily_return * 100 : null]);

		const markLineData: Array<{ name: string; xAxis: string }> = [];
		if (inceptionDate) {
			markLineData.push({ name: "Inception", xAxis: inceptionDate });
		}

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
						const formatted = p.seriesName === "NAV"
							? formatNumber(Number(val), 4)
							: formatPercent(Number(val) / 100);
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
					name: "NAV",
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
			series: [
				{
					name: "NAV",
					type: "line" as const,
					yAxisIndex: 0,
					data: navData,
					smooth: true,
					symbol: "none",
					sampling: "lttb" as const,
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
					type: "bar" as const,
					yAxisIndex: 1,
					data: returnData,
					barMaxWidth: 3,
					barMinWidth: 1,
					itemStyle: {
						color(params: { value?: unknown[] }) {
							const val = Array.isArray(params.value) ? params.value[1] : 0;
							return Number(val) >= 0 ? "rgba(34, 197, 94, 0.45)" : "rgba(239, 68, 68, 0.45)";
						},
					},
					emphasis: { disabled: true },
				},
			],
			legend: {
				show: true,
				bottom: 36,
				data: ["NAV", "Daily Return"],
			},
		};
	});
</script>

{#if isEmpty && !loading}
	<div class="nav-empty">
		<p>No NAV data available — portfolio NAV is synthesized daily by the background worker.</p>
	</div>
{:else}
	<ChartContainer
		{option}
		{height}
		{loading}
		empty={isEmpty}
		emptyMessage="No NAV data available"
		ariaLabel="Portfolio NAV time-series chart"
	/>
{/if}

<style>
	.nav-empty {
		padding: 32px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>

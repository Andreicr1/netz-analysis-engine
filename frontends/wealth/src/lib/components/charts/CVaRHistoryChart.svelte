<!--
  CVaR History Line Chart — dual Y-axis (CVaR % + Utilization %), breach markAreas.
  Uses ChartContainer from @investintell/ui/charts.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { formatPercent, formatDate } from "@investintell/ui";
	import type { CVaRPoint } from "$wealth/stores/risk-store.svelte";

	interface Props {
		data: CVaRPoint[];
		profile: string;
		height?: number;
		loading?: boolean;
	}

	let { data, profile, height = 320, loading = false }: Props = $props();

	let isEmpty = $derived(data.length === 0);

	function extractBreachPeriods(points: CVaRPoint[]) {
		const periods: Array<[{ xAxis: string; name?: string }, { xAxis: string }]> = [];
		let start: string | null = null;
		for (const pt of points) {
			const isBreach = pt.trigger_status === "breach" || pt.trigger_status === "critical" || pt.trigger_status === "hard_stop";
			if (isBreach && !start) {
				start = pt.date;
			} else if (!isBreach && start) {
				periods.push([{ xAxis: start, name: "Breach" }, { xAxis: pt.date }]);
				start = null;
			}
		}
		if (start && points.length > 0) {
			periods.push([{ xAxis: start, name: "Breach" }, { xAxis: points[points.length - 1]!.date }]);
		}
		return periods;
	}

	let option = $derived.by(() => {
		if (isEmpty) return {};

		const dates = data.map((d) => d.date);
		const cvarValues = data.map((d) => [d.date, d.cvar]);
		const limitValues = data.map((d) => [d.date, d.cvar_limit]);
		const utilValues = data.map((d) => [d.date, d.cvar_utilized_pct]);
		const breaches = extractBreachPeriods(data);

		return {
			...globalChartOptions,
			grid: { left: 60, right: 60, top: 40, bottom: 50, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const first = list[0] as { axisValueLabel?: string; value?: unknown[] };
					let html = `<strong>${first.axisValueLabel ?? ""}</strong>`;
					for (const p of list as Array<{ seriesName?: string; value?: unknown[]; color?: string; marker?: string }>) {
						const val = Array.isArray(p.value) ? p.value[1] : p.value;
						if (val == null) continue;
						const formatted = p.seriesName === "Utilization"
							? formatPercent(Number(val) / 100)
							: formatPercent(Number(val));
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
					name: "CVaR %",
					position: "left" as const,
					scale: true,
					alignTicks: true,
					axisLabel: { formatter: "{value}%" },
				},
				{
					type: "value" as const,
					name: "Utilization %",
					position: "right" as const,
					min: 0,
					max: 130,
					alignTicks: true,
					splitLine: { show: false },
					axisLabel: { formatter: "{value}%" },
				},
			],
			visualMap: {
				type: "piecewise" as const,
				show: false,
				seriesIndex: 2,
				dimension: 1,
				pieces: [
					{ lt: 80, color: "#22c55e" },
					{ gte: 80, lt: 100, color: "#f59e0b" },
					{ gte: 100, color: "#ef4444" },
				],
			},
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
					name: "CVaR",
					type: "line" as const,
					yAxisIndex: 0,
					data: cvarValues,
					smooth: true,
					symbol: "none",
					lineStyle: { width: 2 },
					markArea: breaches.length > 0
						? {
							silent: true,
							itemStyle: { color: "rgba(239, 68, 68, 0.08)" },
							data: breaches,
						}
						: undefined,
				},
				{
					name: "Limit",
					type: "line" as const,
					yAxisIndex: 0,
					data: limitValues,
					symbol: "none",
					lineStyle: { width: 1, type: "dashed" as const },
					itemStyle: { color: "#94a3b8" },
				},
				{
					name: "Utilization",
					type: "line" as const,
					yAxisIndex: 1,
					data: utilValues,
					smooth: true,
					symbol: "none",
					lineStyle: { width: 1.5 },
					areaStyle: { opacity: 0.15 },
					markLine: {
						silent: true,
						symbol: "none",
						data: [
							{
								yAxis: 80,
								label: { formatter: "80%", position: "end" as const, fontSize: 9 },
								lineStyle: { color: "#f59e0b", type: "dashed" as const },
							},
							{
								yAxis: 100,
								label: { formatter: "100%", position: "end" as const, fontSize: 9 },
								lineStyle: { color: "#ef4444", type: "dashed" as const },
							},
						],
					},
				},
			],
			legend: {
				show: true,
				bottom: 36,
				data: ["CVaR", "Limit", "Utilization"],
			},
		};
	});
</script>

{#if isEmpty && !loading}
	<div class="cvar-empty">
		<p>No CVaR history available for this profile.</p>
	</div>
{:else}
	<ChartContainer
		{option}
		{height}
		{loading}
		empty={isEmpty}
		emptyMessage="No CVaR history available for this profile"
		ariaLabel="CVaR history chart for {profile} profile"
	/>
{/if}

<style>
	.cvar-empty {
		padding: 32px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>

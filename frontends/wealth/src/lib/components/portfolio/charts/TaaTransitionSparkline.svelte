<!--
  TaaTransitionSparkline — TAA Sprint 4 transition history visualization.

  Shows 60-day smoothed center evolution per asset class group.
  Each sparkline shows how the TAA system has been moving allocation
  centers over time in response to changing market conditions.

  Data from GET /allocation/{profile}/taa-history?limit=60.
  Uses sparklineOptions pattern from echarts-setup.ts.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent, formatShortDate } from "@investintell/ui";
	import type { TaaHistory } from "$wealth/types/taa";
	import { taaRegimeLabel } from "$wealth/types/taa";
	import { BLOCK_GROUPS, groupDisplay } from "$wealth/constants/blocks";
	import { chartTokens } from "$wealth/components/charts/chart-tokens";

	interface Props {
		history: TaaHistory | null;
		loading?: boolean;
		height?: number;
	}

	let { history, loading = false, height = 200 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const isEmpty = $derived(!history || history.rows.length < 2);

	/**
	 * Aggregate smoothed_centers by asset class group.
	 * For each date, sum the smoothed_centers of all blocks in each group.
	 * Returns one line series per group.
	 */
	const option = $derived.by(() => {
		if (isEmpty || !history) return {} as Record<string, unknown>;

		// Rows come newest-first from backend — reverse for chronological
		const rows = [...history.rows].reverse();
		const dates = rows.map((r) => r.as_of_date);

		const groupColors: Record<string, string> = {
			EQUITIES: "#3b82f6",
			"FIXED INCOME": "#22c55e",
			ALTERNATIVES: "#f59e0b",
			"CASH & EQUIVALENTS": "#94a3b8",
		};

		const series = Object.entries(BLOCK_GROUPS).map(([groupName, blockIds]) => {
			const data = rows.map((row) => {
				let sum = 0;
				for (const bid of blockIds) {
					sum += row.smoothed_centers[bid] ?? 0;
				}
				return Math.round(sum * 10000) / 100; // to percent
			});

			return {
				name: groupDisplay(groupName),
				type: "line" as const,
				data,
				smooth: true,
				symbol: "none",
				lineStyle: {
					width: 2,
					color: groupColors[groupName] ?? "#6b7280",
				},
				itemStyle: { color: groupColors[groupName] ?? "#6b7280" },
				areaStyle: {
					color: {
						type: "linear" as const,
						x: 0, y: 0, x2: 0, y2: 1,
						colorStops: [
							{ offset: 0, color: (groupColors[groupName] ?? "#6b7280") + "20" },
							{ offset: 1, color: (groupColors[groupName] ?? "#6b7280") + "05" },
						],
					},
				},
			};
		});

		// Regime background markArea from raw_regime changes
		const markAreaData: Array<[Record<string, unknown>, Record<string, unknown>]> = [];
		let currentRegime = rows[0]?.raw_regime ?? "RISK_ON";
		let startIdx = 0;
		const regimeBgColors: Record<string, string> = {
			RISK_ON: "rgba(34,197,94,0.04)",
			RISK_OFF: "rgba(245,158,11,0.06)",
			CRISIS: "rgba(239,68,68,0.08)",
			INFLATION: "rgba(249,115,22,0.06)",
		};

		for (let i = 1; i < rows.length; i++) {
			const row = rows[i]!;
			if (row.raw_regime !== currentRegime) {
				markAreaData.push([
					{
						xAxis: dates[startIdx]!,
						itemStyle: { color: regimeBgColors[currentRegime] ?? "transparent" },
					},
					{ xAxis: dates[i - 1]! },
				]);
				currentRegime = row.raw_regime;
				startIdx = i;
			}
		}
		// Close last regime
		markAreaData.push([
			{
				xAxis: dates[startIdx]!,
				itemStyle: { color: regimeBgColors[currentRegime] ?? "transparent" },
			},
			{ xAxis: dates[dates.length - 1]! },
		]);

		// Attach markArea to first series
		if (series.length > 0 && markAreaData.length > 0) {
			(series[0] as Record<string, unknown>).markArea = {
				silent: true,
				data: markAreaData,
			};
		}

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
			grid: { left: 8, right: 16, top: 32, bottom: 24, containLabel: true },
			legend: {
				show: true,
				top: 4,
				right: 8,
				textStyle: { color: tokens.axisLabel, fontSize: 10 },
				itemWidth: 14,
				itemHeight: 2,
			},
			tooltip: {
				trigger: "axis" as const,
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				formatter: (params: Array<{ seriesName: string; data: number; axisValue: string; marker: string }>) => {
					if (!Array.isArray(params) || params.length === 0) return "";
					const p0 = params[0]!;
					const dateIdx = dates.indexOf(p0.axisValue);
					const row = dateIdx >= 0 ? rows[dateIdx] : null;
					let header = `<strong>${formatShortDate(p0.axisValue)}</strong>`;
					if (row) {
						header += ` &middot; ${taaRegimeLabel(row.raw_regime)}`;
					}
					const lines = params.map(
						(p) => `${p.marker} ${p.seriesName}: ${formatPercent(p.data / 100, 1)}`,
					);
					return [header, ...lines].join("<br>");
				},
			},
			xAxis: {
				type: "category" as const,
				data: dates,
				axisLabel: {
					color: tokens.axisLabel,
					fontSize: 9,
					formatter: (v: string) => formatShortDate(v),
					interval: Math.max(0, Math.floor(dates.length / 6) - 1),
				},
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			yAxis: {
				type: "value" as const,
				axisLabel: {
					color: tokens.axisLabel,
					fontSize: 10,
					formatter: (v: number) => formatPercent(v / 100, 0),
				},
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" as const } },
			},
			series,
		};
	});
</script>

{#if isEmpty && !loading}
	<p class="taa-spark-empty">
		Transition history requires at least 2 days of regime data.
	</p>
{:else}
	<ChartContainer
		{option}
		{height}
		{loading}
		empty={isEmpty}
		ariaLabel="Transition history showing 60-day allocation center evolution by asset class"
	/>
{/if}

<style>
	.taa-spark-empty {
		margin: 0;
		padding: 16px;
		font-size: 0.75rem;
		color: var(--ii-text-muted, #85a0bd);
		font-style: italic;
		text-align: center;
	}
</style>

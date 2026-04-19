<!--
  AllocationBandChart — TAA Sprint 4 three-layer allocation visualization.

  Shows per-block allocation weights with three visual layers:
    Layer 1 (grey):   IPS outer bounds (hard limits from StrategicAllocation)
    Layer 2 (colored): Regime bands (where the optimizer operates)
    Layer 3 (dots):   Current effective weights (optimizer output)

  Data from GET /allocation/{profile}/effective-with-regime.
  Labels use OD-22 institutional vocabulary, formatPercent from @investintell/ui.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, formatPercent } from "@investintell/ui";
	import type { EffectiveAllocationWithRegime } from "$wealth/types/taa";
	import { taaRegimeLabel, taaRegimeColor } from "$wealth/types/taa";
	import { blockDisplay } from "$wealth/constants/blocks";
	import { chartTokens } from "$wealth/components/charts/chart-tokens";

	interface Props {
		allocations: EffectiveAllocationWithRegime[] | null;
		rawRegime?: string | null;
		loading?: boolean;
		height?: number;
	}

	let { allocations, rawRegime = null, loading = false, height = 280 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const isEmpty = $derived(!allocations || allocations.length === 0);

	/** Resolved regime band color (hex for ECharts, not CSS var). */
	const bandColor = $derived.by(() => {
		if (!rawRegime) return "#3b82f6";
		const map: Record<string, string> = {
			RISK_ON: "#22c55e",
			RISK_OFF: "#f59e0b",
			CRISIS: "#ef4444",
			INFLATION: "#f97316",
		};
		return map[rawRegime] ?? "#3b82f6";
	});

	const option = $derived.by(() => {
		if (isEmpty || !allocations) return {} as Record<string, unknown>;

		const sorted = [...allocations].sort((a, b) => {
			const aw = Number(a.effective_weight ?? 0);
			const bw = Number(b.effective_weight ?? 0);
			return bw - aw;
		});

		const labels = sorted.map((a) => blockDisplay(a.block_id));

		// IPS bounds (grey background bars)
		const ipsMin = sorted.map((a) => Number(a.min_weight ?? 0) * 100);
		const ipsMax = sorted.map((a) => Number(a.max_weight ?? 0) * 100);
		const ipsRange = ipsMin.map((min, i) => [min, ipsMax[i]]);

		// Regime bands (colored inner bars)
		const regimeMin = sorted.map((a) => (a.regime_min ?? Number(a.min_weight ?? 0)) * 100);
		const regimeMax = sorted.map((a) => (a.regime_max ?? Number(a.max_weight ?? 0)) * 100);
		const regimeRange = regimeMin.map((min, i) => [min, regimeMax[i]]);

		// Current weights (scatter dots)
		const weights = sorted.map((a) => Number(a.effective_weight ?? 0) * 100);

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
			grid: { left: 12, right: 20, top: 36, bottom: 24, containLabel: true },
			legend: {
				show: true,
				top: 4,
				right: 8,
				textStyle: { color: tokens.axisLabel, fontSize: 10 },
				itemWidth: 12,
				itemHeight: 8,
				data: [
					{ name: "IPS Bounds" },
					{ name: rawRegime ? taaRegimeLabel(rawRegime) + " Band" : "Regime Band" },
					{ name: "Current Weight" },
				],
			},
			tooltip: {
				trigger: "axis" as const,
				axisPointer: { type: "shadow" as const },
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				formatter: (params: Array<{ seriesName: string; data: unknown; axisValue: string }>) => {
					if (!Array.isArray(params) || params.length === 0) return "";
					const p0 = params[0];
					if (!p0) return "";
					const idx = labels.indexOf(p0.axisValue);
					if (idx < 0) return "";
					const a = sorted[idx]!;
					const lines = [
						`<strong>${p0.axisValue}</strong>`,
						`IPS: ${formatPercent(Number(a.min_weight ?? 0), 1)} \u2013 ${formatPercent(Number(a.max_weight ?? 0), 1)}`,
					];
					if (a.regime_min != null && a.regime_max != null) {
						lines.push(
							`${rawRegime ? taaRegimeLabel(rawRegime) : "Regime"}: ${formatPercent(a.regime_min, 1)} \u2013 ${formatPercent(a.regime_max, 1)}`,
						);
					}
					lines.push(`Current: ${formatPercent(Number(a.effective_weight ?? 0), 1)}`);
					return lines.join("<br>");
				},
			},
			xAxis: {
				type: "category" as const,
				data: labels,
				axisLabel: {
					color: tokens.axisLabel,
					fontSize: 10,
					rotate: labels.length > 8 ? 35 : 0,
					interval: 0,
				},
				axisLine: { lineStyle: { color: tokens.grid } },
				axisTick: { show: false },
			},
			yAxis: {
				type: "value" as const,
				name: "Weight",
				nameTextStyle: { color: tokens.axisLabel, fontSize: 10 },
				axisLabel: {
					color: tokens.axisLabel,
					fontSize: 10,
					formatter: (v: number) => formatPercent(v / 100, 0),
				},
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" as const } },
			},
			series: [
				// Layer 1: IPS bounds (grey range bar)
				{
					name: "IPS Bounds",
					type: "bar",
					barWidth: "60%",
					barGap: "-100%",
					itemStyle: {
						color: "rgba(128, 128, 128, 0.15)",
						borderColor: "rgba(128, 128, 128, 0.3)",
						borderWidth: 1,
						borderRadius: [3, 3, 3, 3],
					},
					data: ipsRange,
					z: 1,
				},
				// Layer 2: Regime bands (colored inner range)
				{
					name: rawRegime ? taaRegimeLabel(rawRegime) + " Band" : "Regime Band",
					type: "bar",
					barWidth: "40%",
					barGap: "-100%",
					itemStyle: {
						color: bandColor + "33",
						borderColor: bandColor,
						borderWidth: 1.5,
						borderRadius: [2, 2, 2, 2],
					},
					data: regimeRange,
					z: 2,
				},
				// Layer 3: Current effective weights (scatter dots)
				{
					name: "Current Weight",
					type: "scatter",
					symbolSize: 10,
					itemStyle: {
						color: "#ffffff",
						borderColor: bandColor,
						borderWidth: 2,
					},
					data: weights,
					z: 3,
				},
			],
		};
	});
</script>

{#if isEmpty && !loading}
	<EmptyState
		title="No allocation data"
		message="Allocation bands will appear after the engine computes regime-adjusted weights."
	/>
{:else}
	<ChartContainer
		{option}
		{height}
		{loading}
		empty={isEmpty}
		ariaLabel="Allocation band chart showing IPS bounds, regime bands, and current weights"
	/>
{/if}

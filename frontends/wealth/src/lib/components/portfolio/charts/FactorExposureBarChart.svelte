<!--
  FactorExposureBarChart — Phase 6 Block B portfolio-specific chart.

  Renders the portfolio's PCA / style factor exposures as a horizontal
  bar chart with diverging colors (positive = success, negative = danger).
  Reads ``factor_analysis.portfolio_factor_exposures`` (preferred — the
  /analytics/factor-analysis/{profile} response) and falls back to
  ``construction_run.factor_exposure`` JSONB if the analytics route did
  not return data (e.g. portfolio is not yet live).

  Per CLAUDE.md DL16 — every loading goes through formatNumber. Per
  OD-26 — strict empty state when neither source has data.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, formatNumber } from "@investintell/ui";
	import type { FactorAnalysisResponse } from "$wealth/state/portfolio-workspace.svelte";
	import type { ConstructionRunPayload } from "$wealth/state/portfolio-workspace.svelte";
	import { chartTokens } from "$wealth/components/charts/chart-tokens";

	interface Props {
		factorAnalysis: FactorAnalysisResponse | null;
		latestRun: ConstructionRunPayload | null;
		height?: number;
	}

	let { factorAnalysis, latestRun, height = 320 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const exposures = $derived.by<Array<{ label: string; value: number }>>(() => {
		// Preferred source: /analytics/factor-analysis route
		if (factorAnalysis?.portfolio_factor_exposures) {
			return Object.entries(factorAnalysis.portfolio_factor_exposures).map(
				([label, value]) => ({
					label,
					value: Number(value),
				}),
			);
		}
		// Fallback: construction_run.factor_exposure JSONB. Shape may be
		// either a flat dict or a nested {exposures: {...}} object.
		const fe = latestRun?.factor_exposure;
		if (fe && typeof fe === "object") {
			const inner = (fe as Record<string, unknown>).exposures ?? fe;
			if (inner && typeof inner === "object") {
				return Object.entries(inner as Record<string, unknown>)
					.filter(([, v]) => typeof v === "number")
					.map(([label, v]) => ({ label, value: v as number }));
			}
		}
		return [];
	});

	const isEmpty = $derived(exposures.length === 0);

	const option = $derived.by(() => {
		if (isEmpty) return {} as Record<string, unknown>;

		const sorted = [...exposures].sort(
			(a, b) => Math.abs(b.value) - Math.abs(a.value),
		);
		const labels = sorted.map((e) => e.label);
		const values = sorted.map((e) => Math.round(e.value * 1000) / 1000);

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
			grid: { left: 140, right: 50, top: 12, bottom: 24, containLabel: false },
			tooltip: {
				trigger: "axis" as const,
				axisPointer: { type: "shadow" as const },
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				valueFormatter: (v: number) =>
					`${v >= 0 ? "+" : ""}${formatNumber(v, 3)}`,
			},
			xAxis: {
				type: "value" as const,
				min: -1,
				max: 1,
				axisLabel: {
					formatter: (v: number) => formatNumber(v, 1),
					fontSize: 10,
					color: tokens.axisLabel,
				},
				splitLine: {
					lineStyle: { type: "dashed" as const, color: "rgba(64,66,73,0.3)" },
				},
			},
			yAxis: {
				type: "category" as const,
				data: labels,
				inverse: true,
				axisLabel: { fontSize: 12, fontWeight: 600, color: "#cbccd1" },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					type: "bar" as const,
					barWidth: "55%",
					data: values.map((v) => ({
						value: v,
						itemStyle: {
							color: v >= 0 ? tokens.positive : tokens.negative,
							borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
						},
					})),
					label: {
						show: true,
						position: "right" as const,
						fontSize: 11,
						fontWeight: 600,
						color: "#ffffff",
						formatter: (p: { value: number }) =>
							`${p.value > 0 ? "+" : ""}${formatNumber(p.value, 2)}`,
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: "#71717a", type: "solid" as const, width: 1 },
						label: { show: false },
					},
				},
			],
		} as Record<string, unknown>;
	});
</script>

{#if isEmpty}
	<EmptyState
		title="No factor exposures"
		message="Activate the portfolio to compute factor analysis, or run a construction with factor analysis enabled."
	/>
{:else}
	<ChartContainer {option} {height} ariaLabel="Style factor exposures" />
{/if}

<!--
  ConstituentCorrelationHeatmap — Phase 6 Block B portfolio-specific
  chart.

  Renders the Marchenko-Pastur denoised constituent correlation matrix
  as an ECharts heatmap. Diverging color scale (positive=primary,
  negative=danger, zero=neutral) so the contagion / clustering pattern
  is immediately readable.

  Data source: CorrelationRegimeResult from
  GET /analytics/correlation-regime/{profile} (recon §1). The matrix
  is N×N square, indexed by ``instrument_labels`` on both axes. The
  service applies Ledoit-Wolf 2003 constant-correlation shrinkage AND
  Marchenko-Pastur denoising before returning the matrix.

  Per CLAUDE.md DL16 — every coefficient goes through formatNumber.
  Per OD-26 — strict empty state when no correlation data.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, formatNumber } from "@investintell/ui";
	import type { CorrelationRegimeResult } from "$wealth/types/analytics";
	import { chartTokens } from "$wealth/components/charts/chart-tokens";

	interface Props {
		correlation: CorrelationRegimeResult | null;
		height?: number;
	}

	let { correlation, height = 360 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const matrix = $derived(correlation?.correlation_matrix ?? []);
	const labels = $derived(correlation?.instrument_labels ?? []);
	const isEmpty = $derived(matrix.length === 0 || labels.length === 0);

	const option = $derived.by(() => {
		if (isEmpty) return {} as Record<string, unknown>;

		// Flatten the N×N matrix into [x, y, value] triplets ECharts
		// heatmap expects.
		const data: Array<[number, number, number]> = [];
		for (let i = 0; i < matrix.length; i++) {
			const row = matrix[i];
			if (!row) continue;
			for (let j = 0; j < row.length; j++) {
				const value = row[j];
				if (value === undefined) continue;
				data.push([j, i, Math.round(value * 1000) / 1000]);
			}
		}

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
			tooltip: {
				position: "top" as const,
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				formatter: (params: { data: [number, number, number] }) => {
					const [x, y, v] = params.data;
					const a = labels[y] ?? `#${y}`;
					const b = labels[x] ?? `#${x}`;
					return `<strong>${a}</strong> ↔ <strong>${b}</strong><br/>ρ = ${formatNumber(v, 3)}`;
				},
			},
			grid: {
				left: 120,
				right: 50,
				top: 16,
				bottom: 80,
				containLabel: false,
			},
			xAxis: {
				type: "category" as const,
				data: labels,
				splitArea: { show: true },
				axisLabel: {
					fontSize: 10,
					color: tokens.axisLabel,
					rotate: 45,
					interval: 0,
					formatter: (v: string) => (v.length > 14 ? v.slice(0, 12) + "…" : v),
				},
			},
			yAxis: {
				type: "category" as const,
				data: labels,
				splitArea: { show: true },
				axisLabel: {
					fontSize: 10,
					color: tokens.axisLabel,
					formatter: (v: string) => (v.length > 14 ? v.slice(0, 12) + "…" : v),
				},
			},
			visualMap: {
				min: -1,
				max: 1,
				calculable: true,
				orient: "horizontal" as const,
				left: "center" as const,
				bottom: 8,
				itemHeight: 100,
				textStyle: { color: tokens.axisLabel, fontSize: 10 },
				inRange: {
					color: [tokens.negative, "#1a1b20", tokens.primary],
				},
			},
			series: [
				{
					name: "Correlation",
					type: "heatmap" as const,
					data,
					label: {
						show: labels.length <= 12,
						fontSize: 9,
						color: "#ffffff",
						formatter: (params: { data: [number, number, number] }) =>
							formatNumber(params.data[2], 2),
					},
					emphasis: {
						itemStyle: {
							shadowBlur: 8,
							shadowColor: "rgba(255,255,255,0.3)",
						},
					},
				},
			],
		} as Record<string, unknown>;
	});
</script>

{#if isEmpty}
	<EmptyState
		title="No correlation matrix"
		message="Activate the portfolio with at least 2 constituents to compute the denoised correlation regime. The route requires a live model_portfolio for that profile."
	/>
{:else}
	<header class="cch-header">
		<div class="cch-stat">
			<span class="cch-kicker">Avg correlation</span>
			<span class="cch-value">{formatNumber(correlation?.average_correlation ?? 0, 3)}</span>
		</div>
		<div class="cch-stat">
			<span class="cch-kicker">Constituents</span>
			<span class="cch-value">{correlation?.instrument_count ?? 0}</span>
		</div>
		{#if correlation?.regime_shift_detected}
			<div class="cch-stat cch-stat--alert">
				<span class="cch-kicker">Regime shift</span>
				<span class="cch-value">Detected</span>
			</div>
		{/if}
	</header>
	<ChartContainer
		{option}
		{height}
		ariaLabel="Constituent correlation heatmap"
	/>
{/if}

<style>
	.cch-header {
		display: flex;
		gap: 24px;
		margin-bottom: 8px;
	}
	.cch-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.cch-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.cch-value {
		font-size: 16px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
	.cch-stat--alert .cch-value {
		color: var(--ii-warning, #f0a020);
	}
</style>

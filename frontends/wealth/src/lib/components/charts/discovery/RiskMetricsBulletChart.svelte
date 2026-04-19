<!--
  RiskMetricsBulletChart — institutional bullet chart rendering the 4 risk
  metrics the backend exposes on `fund_risk_metrics` (post 2026-04-08 contract
  lock): risk-adjusted return (sharpe_1y), volatility (volatility_1y), worst
  drawdown (max_drawdown_1y), and downside scenario loss (cvar_95_12m).

  Peer markers come from the same payload: when backend supplies the percentile
  rank (peer_sharpe_pctl / peer_drawdown_pctl) we use it as a reference marker.

  Smart-backend/dumb-frontend: all user-visible labels are institutional plain
  English — no Sharpe, CVaR, Sortino, Beta jargon leaks to the UI.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import type { RiskMetricsPayload } from "$wealth/discovery/analysis-api";
	import { chartTokens } from "../chart-tokens";

	interface Props {
		metrics: RiskMetricsPayload | null;
		height?: number;
	}

	let { metrics, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const rows = $derived.by(() => {
		const m = metrics ?? ({} as Partial<RiskMetricsPayload>);
		const defs: {
			label: string;
			actual: number | null | undefined;
			peer: number | null | undefined;
		}[] = [
			{
				label: "Risk-adjusted return",
				actual: m.sharpe_1y,
				peer: m.peer_sharpe_pctl,
			},
			{
				label: "Volatility",
				actual: m.volatility_1y,
				peer: null,
			},
			{
				label: "Worst drawdown (1y)",
				actual: m.max_drawdown_1y,
				peer: m.peer_drawdown_pctl,
			},
			{
				label: "Downside scenario loss (95%)",
				actual: m.cvar_95_12m,
				peer: null,
			},
		];
		return defs.map((d) => ({
			label: d.label,
			actual: typeof d.actual === "number" ? d.actual : null,
			peer: typeof d.peer === "number" ? d.peer : null,
		}));
	});

	const hasData = $derived(rows.some((r) => r.actual != null));

	const option = $derived.by(() => {
		const categories = rows.map((r) => r.label);
		const actuals = rows.map((r) => r.actual ?? 0);
		const peerMarkers = rows
			.map((r, idx) =>
				r.peer != null ? { xAxis: r.peer, yAxis: idx } : null,
			)
			.filter((x): x is { xAxis: number; yAxis: number } => x !== null);

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
			},
			grid: { left: 180, right: 40, top: 16, bottom: 24 },
			xAxis: {
				type: "value",
				axisLabel: { color: tokens.axisLabel },
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
			},
			yAxis: {
				type: "category",
				data: categories,
				axisLabel: { color: tokens.axisLabel, fontSize: 11 },
				axisLine: { lineStyle: { color: tokens.grid } },
			},
			series: [
				{
					name: "Fund",
					type: "bar",
					data: actuals,
					itemStyle: { color: tokens.primary },
					barWidth: 14,
					markPoint: {
						symbol: "pin",
						symbolSize: 18,
						itemStyle: { color: tokens.benchmark },
						label: { show: false },
						data: peerMarkers,
					},
				},
			],
			animationDuration: 300,
		};
	});
</script>

{#if !hasData}
	<ChartContainer
		option={{}}
		{height}
		empty
		emptyMessage="Risk metrics not available for this fund."
		ariaLabel="How this fund compares on risk"
	/>
{:else}
	<ChartContainer
		{option}
		{height}
		ariaLabel="How this fund compares on risk"
	/>
{/if}

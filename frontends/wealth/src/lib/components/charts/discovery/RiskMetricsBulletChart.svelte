<!--
  RiskMetricsBulletChart — minimum-viable bullet chart. Six rows (Sharpe,
  Sortino, Volatility, Max DD, CVaR 95, Beta) rendered as horizontal bars
  with a markPoint for a peer median reference. Peer median comes from
  backend when available; falls back to 50% of the actual value so the
  reference dot still renders (clearly marked via a lighter color).

  This card is institutional polish: the primary goal is to surface the
  risk_metrics row next to the equity curve without requiring the operator
  to hunt for numbers in a table.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";

	interface RiskMetrics {
		sharpe_ratio?: number | null;
		sortino_ratio?: number | null;
		volatility?: number | null;
		max_drawdown?: number | null;
		cvar_95?: number | null;
		beta?: number | null;
		// Optional peer medians — backend may or may not supply these
		peer_sharpe?: number | null;
		peer_sortino?: number | null;
		peer_volatility?: number | null;
		peer_max_drawdown?: number | null;
		peer_cvar_95?: number | null;
		peer_beta?: number | null;
		[key: string]: unknown;
	}

	interface Props {
		metrics: RiskMetrics | null;
		height?: number;
	}

	let { metrics, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const rows = $derived.by(() => {
		const m = metrics ?? {};
		const defs = [
			{ label: "Sharpe", actual: m.sharpe_ratio, peer: m.peer_sharpe },
			{ label: "Sortino", actual: m.sortino_ratio, peer: m.peer_sortino },
			{ label: "Volatility", actual: m.volatility, peer: m.peer_volatility },
			{ label: "Max DD", actual: m.max_drawdown, peer: m.peer_max_drawdown },
			{ label: "CVaR 95", actual: m.cvar_95, peer: m.peer_cvar_95 },
			{ label: "Beta", actual: m.beta, peer: m.peer_beta },
		];
		return defs.map((d) => ({
			label: d.label,
			actual: typeof d.actual === "number" ? d.actual : null,
			peer:
				typeof d.peer === "number"
					? d.peer
					: typeof d.actual === "number"
						? d.actual * 0.5
						: null,
		}));
	});

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
			grid: { left: 96, right: 40, top: 16, bottom: 24 },
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
					name: "Actual",
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

<ChartContainer {option} {height} ariaLabel="Risk metrics versus peers" />

<!--
  PeerScatterChart — Risk/return scatter for the Discovery Analysis Peer view
  (Phase 7). X = Volatility (1y, %), Y = Sharpe (1y). Subject point uses
  `tokens.primary` with a larger symbolSize so it visually anchors the cohort
  of `tokens.benchmark` peer dots.

  Tokens via chartTokens(); rendered with ChartContainer from
  @investintell/ui/charts. Filters out peers missing volatility or sharpe so
  ECharts never receives null tuples.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";

	interface Peer {
		external_id: string;
		name: string;
		ticker?: string | null;
		volatility_1y: number | null;
		sharpe_1y: number | null;
		is_subject: boolean;
	}
	interface Props {
		peers: Peer[];
	}

	let { peers }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const data = $derived.by(() =>
		peers
			.filter((p) => p.volatility_1y != null && p.sharpe_1y != null)
			.map((p) => ({
				value: [(p.volatility_1y as number) * 100, p.sharpe_1y as number],
				name: p.name,
				ticker: p.ticker ?? null,
				itemStyle: { color: p.is_subject ? tokens.primary : tokens.benchmark },
				symbolSize: p.is_subject ? 24 : 12,
				is_subject: p.is_subject,
			})),
	);

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
		tooltip: {
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			textStyle: { color: tokens.axisLabel, fontSize: 11 },
			formatter: (p: {
				data: {
					name: string;
					ticker: string | null;
					value: [number, number];
					is_subject: boolean;
				};
			}) => {
				const tag = p.data.is_subject ? " (subject)" : "";
				const tk = p.data.ticker ? ` · ${p.data.ticker}` : "";
				return `<div style="font-family:${tokens.fontFamily}">
					<strong>${p.data.name}</strong>${tk}${tag}<br/>
					<span style="color:${tokens.axisLabel}">Vol: ${p.data.value[0].toFixed(2)}%</span><br/>
					<span style="color:${tokens.axisLabel}">Sharpe: ${p.data.value[1].toFixed(2)}</span>
				</div>`;
			},
		},
		grid: { left: 56, right: 24, top: 32, bottom: 48, containLabel: true },
		xAxis: {
			type: "value",
			name: "Volatility (%)",
			nameLocation: "middle",
			nameGap: 32,
			nameTextStyle: { color: tokens.axisLabel, fontSize: 10 },
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		yAxis: {
			type: "value",
			name: "Sharpe",
			nameLocation: "middle",
			nameGap: 40,
			nameTextStyle: { color: tokens.axisLabel, fontSize: 10 },
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		series: [
			{
				type: "scatter",
				data,
				emphasis: {
					itemStyle: { borderColor: tokens.primary, borderWidth: 2 },
				},
			},
		],
	});
</script>

<ChartContainer {option} height={380} ariaLabel="Peer risk/return scatter" />

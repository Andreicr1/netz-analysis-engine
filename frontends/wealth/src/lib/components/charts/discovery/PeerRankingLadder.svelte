<!--
  PeerRankingLadder — Horizontal bar chart ranking peers by Sharpe (1y) DESC.
  Subject row uses `tokens.primary`, others use `tokens.benchmark`. Truncates
  long fund names to 25 chars on the y-axis label. Inverse y-axis so the
  highest Sharpe sits at the top.

  Tokens via chartTokens(); rendered with ChartContainer from
  @investintell/ui/charts. Per-item color via callback on series itemStyle.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";

	interface Peer {
		external_id: string;
		name: string;
		ticker?: string | null;
		sharpe_1y: number | null;
		is_subject: boolean;
	}
	interface Props {
		peers: Peer[];
	}

	let { peers }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const sortedPeers = $derived.by(() =>
		[...peers]
			.filter((p) => p.sharpe_1y != null)
			.sort((a, b) => (b.sharpe_1y ?? 0) - (a.sharpe_1y ?? 0))
			.slice(0, 20),
	);

	function truncate(s: string, n: number): string {
		return s.length > n ? `${s.slice(0, n - 1)}…` : s;
	}

	const labels = $derived(sortedPeers.map((p) => truncate(p.name, 25)));

	const data = $derived(
		sortedPeers.map((p) => ({
			value: p.sharpe_1y as number,
			name: p.name,
			is_subject: p.is_subject,
			itemStyle: { color: p.is_subject ? tokens.primary : tokens.benchmark },
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
			formatter: (p: { data: { name: string; value: number; is_subject: boolean } }) => {
				const tag = p.data.is_subject ? " (subject)" : "";
				return `<strong>${p.data.name}</strong>${tag}<br/>Sharpe: ${p.data.value.toFixed(2)}`;
			},
		},
		grid: { left: 8, right: 24, top: 16, bottom: 32, containLabel: true },
		xAxis: {
			type: "value",
			name: "Sharpe (1y)",
			nameLocation: "middle",
			nameGap: 24,
			nameTextStyle: { color: tokens.axisLabel, fontSize: 10 },
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		yAxis: {
			type: "category",
			inverse: true,
			data: labels,
			axisLabel: { color: tokens.axisLabel, fontSize: 10 },
			axisLine: { lineStyle: { color: tokens.grid } },
			axisTick: { show: false },
		},
		series: [
			{
				type: "bar",
				data,
				barMaxWidth: 14,
				emphasis: {
					itemStyle: { borderColor: tokens.primary, borderWidth: 2 },
				},
			},
		],
	});
</script>

<ChartContainer {option} height={380} ariaLabel="Peer Sharpe ranking ladder" />

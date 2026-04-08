<!--
  SectorTreemap — ECharts treemap of sector weights from the holdings/top
  `sector_breakdown` array. Label formatter uses sector name + percent; tooltip
  uses formatPercent. No inline hex, no toFixed on user-visible percentages.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface Sector {
		sector: string;
		weight: number;
		holdings_count: number;
	}
	interface Props {
		sectors: Sector[];
		height?: number;
	}

	let { sectors, height = 360 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const data = $derived(
		sectors.map((s) => ({
			name: s.sector,
			value: s.weight,
			holdings_count: s.holdings_count,
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
				name?: string;
				value?: number;
				data?: { holdings_count?: number };
			}) => {
				const w = typeof p.value === "number" ? formatPercent(p.value, 2) : "—";
				const count = p.data?.holdings_count ?? 0;
				return `<strong>${p.name ?? ""}</strong><br/>${w} · ${count} holdings`;
			},
		},
		series: [
			{
				type: "treemap",
				data,
				roam: false,
				nodeClick: false,
				breadcrumb: { show: false },
				label: {
					show: true,
					formatter: (p: { name?: string; value?: number }) => {
						const pct =
							typeof p.value === "number"
								? `${(p.value * 100).toFixed(1)}%`
								: "";
						return `${p.name ?? ""}\n${pct}`;
					},
					color: "#ffffff",
					fontSize: 11,
					fontWeight: 600,
				},
				itemStyle: {
					borderColor: tokens.tooltipBg,
					borderWidth: 2,
					gapWidth: 2,
				},
				upperLabel: { show: false },
				levels: [
					{
						itemStyle: { borderColor: tokens.tooltipBg, borderWidth: 2 },
					},
				],
			},
		],
	});
</script>

<ChartContainer {option} {height} ariaLabel="Sector composition treemap" />

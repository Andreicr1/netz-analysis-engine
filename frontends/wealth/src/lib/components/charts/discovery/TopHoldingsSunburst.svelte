<!--
  TopHoldingsSunburst — two-level sunburst: outer ring = sector, inner ring =
  top holdings (issuer names). Built from the holdings/top payload. Uses
  formatPercent in tooltip; no toFixed on user-facing values.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface Holding {
		issuer_name: string;
		cusip: string | null;
		sector: string | null;
		weight: number;
		market_value: number | null;
	}
	interface Props {
		holdings: Holding[];
		height?: number;
	}

	let { holdings, height = 360 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const data = $derived.by(() => {
		const bySector = new Map<string, { name: string; value: number }[]>();
		for (const h of holdings) {
			const sec = h.sector ?? "Unknown";
			if (!bySector.has(sec)) bySector.set(sec, []);
			bySector.get(sec)!.push({
				name: h.issuer_name,
				value: h.weight,
			});
		}
		return Array.from(bySector.entries()).map(([sector, items]) => ({
			name: sector,
			children: items,
		}));
	});

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
		tooltip: {
			trigger: "item",
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			textStyle: { color: tokens.axisLabel, fontSize: 11 },
			formatter: (p: { name?: string; value?: number }) => {
				const w = typeof p.value === "number" ? formatPercent(p.value, 2) : "—";
				return `<strong>${p.name ?? ""}</strong><br/>${w}`;
			},
		},
		series: [
			{
				type: "sunburst",
				data,
				radius: ["20%", "90%"],
				sort: undefined,
				label: {
					color: tokens.axisLabel,
					fontSize: 10,
					rotate: "tangential",
				},
				itemStyle: {
					borderColor: tokens.tooltipBg,
					borderWidth: 1,
				},
				levels: [
					{},
					{
						r0: "20%",
						r: "55%",
						itemStyle: { color: tokens.primary, opacity: 0.85 },
						label: { rotate: "tangential" },
					},
					{
						r0: "55%",
						r: "90%",
						itemStyle: { opacity: 0.7 },
						label: { align: "right" },
					},
				],
				emphasis: { focus: "ancestor" },
			},
		],
	});
</script>

<ChartContainer {option} {height} ariaLabel="Top holdings sunburst by sector" />

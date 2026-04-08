<!--
  HoldingsNetworkChart — ECharts force-directed graph for the Holdings Reverse
  Lookup view (Discovery FCL Phase 6). Renders a "Les Misérables"-style network
  with one central holding node (CUSIP / issuer) and N holder nodes (13F/NPORT
  filers) connected by edges weighted by market value.

  Tokens via chartTokens(); no inline hex. Driven by the reverse-lookup payload
  (`{nodes, edges}`) from analysis-api.fetchReverseLookup.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";

	interface Node {
		id: string;
		name: string;
		category: "holding" | "holder";
		symbolSize: number;
		value?: number;
		source?: string;
	}
	interface Edge {
		source: string;
		target: string;
	}
	interface Props {
		nodes: Node[];
		edges: Edge[];
		height?: number;
	}

	let { nodes, edges, height = 480 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
		tooltip: {
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			textStyle: { color: tokens.axisLabel, fontSize: 11 },
			formatter: (p: { dataType?: string; data?: { name?: string; value?: number; source?: string } }) => {
				if (p.dataType === "edge") return "";
				const d = p.data ?? {};
				const src = d.source ? ` · ${String(d.source).toUpperCase()}` : "";
				const val = typeof d.value === "number" ? `<br/>$${(d.value / 1e6).toFixed(1)}M` : "";
				return `<strong>${d.name ?? ""}</strong>${src}${val}`;
			},
		},
		legend: [
			{
				data: ["Holding", "Holder"],
				textStyle: { color: tokens.axisLabel },
				bottom: 8,
			},
		],
		series: [
			{
				type: "graph",
				layout: "force",
				force: { repulsion: 120, edgeLength: [60, 140], gravity: 0.1 },
				roam: true,
				draggable: true,
				label: {
					show: true,
					position: "right",
					color: tokens.axisLabel,
					fontSize: 10,
				},
				categories: [
					{ name: "Holding", itemStyle: { color: tokens.primary } },
					{ name: "Holder", itemStyle: { color: tokens.benchmark } },
				],
				data: nodes.map((n) => ({
					id: n.id,
					name: n.name,
					symbolSize: n.symbolSize,
					category: n.category === "holding" ? 0 : 1,
					value: n.value,
					source: n.source,
				})),
				edges: edges.map((e) => ({
					source: e.source,
					target: e.target,
					lineStyle: { color: tokens.grid, width: 1, curveness: 0.15 },
				})),
				emphasis: {
					focus: "adjacency",
					lineStyle: { width: 2, color: tokens.primary },
				},
				animationDurationUpdate: 500,
			},
		],
	});
</script>

<ChartContainer {option} {height} ariaLabel="Holdings reverse lookup network" />

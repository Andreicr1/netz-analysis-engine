<!--
  StyleDriftFlow — stacked area chart showing how sector weights evolve across
  the last N quarters. One series per unique sector across all snapshots; each
  series is stacked on the same key so the area chart totals to 100% (sectors
  sum to fund NAV per snapshot).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface SectorPoint {
		name: string;
		weight: number;
	}
	interface Snapshot {
		quarter: string;
		sectors: SectorPoint[];
	}
	interface Props {
		snapshots: Snapshot[];
		height?: number;
	}

	let { snapshots, height = 360 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const allSectors = $derived.by(() => {
		const set = new Set<string>();
		for (const s of snapshots) {
			for (const sec of s.sectors) set.add(sec.name);
		}
		return Array.from(set).sort();
	});

	const quarters = $derived(snapshots.map((s) => s.quarter));

	const series = $derived.by(() =>
		allSectors.map((sectorName) => ({
			name: sectorName,
			type: "line",
			stack: "total",
			areaStyle: { opacity: 0.8 },
			lineStyle: { width: 1 },
			showSymbol: false,
			emphasis: { focus: "series" },
			data: snapshots.map((snap) => {
				const found = snap.sectors.find((s) => s.name === sectorName);
				return found ? found.weight : 0;
			}),
		})),
	);

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
		tooltip: {
			trigger: "axis",
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			textStyle: { color: tokens.axisLabel, fontSize: 11 },
			valueFormatter: (v: number) => formatPercent(v, 1),
		},
		legend: {
			data: allSectors,
			textStyle: { color: tokens.axisLabel, fontSize: 10 },
			bottom: 0,
			type: "scroll",
		},
		grid: { left: 48, right: 24, top: 24, bottom: 56 },
		xAxis: {
			type: "category",
			data: quarters,
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
			boundaryGap: false,
		},
		yAxis: {
			type: "value",
			max: 1,
			axisLabel: {
				color: tokens.axisLabel,
				formatter: (v: number) => formatPercent(v, 0),
			},
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		series,
		animationDuration: 400,
	});
</script>

<ChartContainer {option} {height} ariaLabel="Sector style drift across quarters" />

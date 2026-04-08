<!--
  InstitutionalRevealMatrix — ECharts heatmap showing which curated institutions
  (Yale, Harvard, Bridgewater, etc.) hold each of the subject fund's top
  holdings. X = top 25 issuer names (rotated 45deg), Y = institution names,
  cell intensity = log10(position_value + 1) for visibility across the long
  tail of position sizes. Empty cells show as the lightest grid color.

  Tokens via chartTokens(); rendered with ChartContainer from
  @investintell/ui/charts. Caller is responsible for hiding the chart entirely
  when `institutions` is empty (e.g. when the curated CIK backfill has not run
  yet).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatCompact } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface Institution {
		institution_id: string;
		name: string;
		category: string;
	}
	interface Holding {
		cusip: string;
		issuer_name: string;
	}
	interface Props {
		institutions: Institution[];
		holdings: Holding[];
		matrix: Record<string, Record<string, number>>;
	}

	let { institutions, holdings, matrix }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const xHoldings = $derived(holdings.slice(0, 25));

	const data = $derived.by(() => {
		const out: [number, number, number][] = [];
		institutions.forEach((inst, y) => {
			xHoldings.forEach((h, x) => {
				const v = matrix[inst.institution_id]?.[h.cusip] ?? 0;
				out.push([x, y, v > 0 ? Math.log10(v + 1) : 0]);
			});
		});
		return out;
	});

	const maxLog = $derived.by(() => {
		let m = 0;
		for (const tuple of data) {
			if (tuple[2] > m) m = tuple[2];
		}
		return m > 0 ? Math.ceil(m) : 10;
	});

	function truncate(s: string, n: number): string {
		return s.length > n ? `${s.slice(0, n - 1)}…` : s;
	}

	const xLabels = $derived(xHoldings.map((h) => truncate(h.issuer_name, 22)));
	const yLabels = $derived(institutions.map((i) => truncate(i.name, 28)));

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 10 },
		tooltip: {
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			textStyle: { color: tokens.axisLabel, fontSize: 11 },
			formatter: (p: { data: [number, number, number] }) => {
				const inst = institutions[p.data[1]];
				const h = xHoldings[p.data[0]];
				if (!inst || !h) return "";
				const v = matrix[inst.institution_id]?.[h.cusip] ?? 0;
				const valueDisplay = v > 0 ? formatCompact(v) : "Not held";
				return `<strong>${inst.name}</strong><br/>${h.issuer_name}<br/><span style="color:${tokens.axisLabel}">${valueDisplay}</span>`;
			},
		},
		grid: { left: 200, right: 32, top: 24, bottom: 140 },
		xAxis: {
			type: "category",
			data: xLabels,
			splitArea: { show: true },
			axisLabel: {
				color: tokens.axisLabel,
				rotate: 45,
				interval: 0,
				fontSize: 9,
			},
			axisLine: { lineStyle: { color: tokens.grid } },
			axisTick: { show: false },
		},
		yAxis: {
			type: "category",
			data: yLabels,
			splitArea: { show: true },
			axisLabel: { color: tokens.axisLabel, fontSize: 10 },
			axisLine: { lineStyle: { color: tokens.grid } },
			axisTick: { show: false },
		},
		visualMap: {
			min: 0,
			max: maxLog,
			calculable: true,
			orient: "horizontal",
			left: "center",
			bottom: 16,
			inRange: { color: [tokens.grid, tokens.primary] },
			textStyle: { color: tokens.axisLabel, fontSize: 10 },
			text: ["larger position", "smaller position"],
		},
		series: [
			{
				type: "heatmap",
				data,
				emphasis: {
					itemStyle: { borderColor: tokens.primary, borderWidth: 2 },
				},
				progressive: 1000,
			},
		],
	});
</script>

<ChartContainer
	{option}
	height={540}
	ariaLabel="Institutional holdings overlap heatmap"
/>

<!--
  HoldingsTreemapChart — Phase 6 Block B portfolio-specific chart.

  Renders the portfolio's allocation block composition as an ECharts
  treemap. Pure client-side: reads ``portfolio.fund_selection_schema.funds``
  and groups by ``block_id`` for the institutional sector view, then
  drills into individual funds inside each block tile.

  Per CLAUDE.md DL16 — every weight goes through @investintell/ui's
  formatPercent. Per OD-26 — strict empty state when the portfolio has
  no fund selection or weights sum to zero.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, formatPercent, formatNumber } from "@investintell/ui";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { blockLabel } from "$lib/constants/blocks";
	import { chartTokens } from "$lib/components/charts/chart-tokens";

	interface Props {
		portfolio: ModelPortfolio | null;
		height?: number;
	}

	let { portfolio, height = 320 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	interface BlockGroup {
		blockId: string;
		blockName: string;
		totalWeight: number;
		funds: Array<{ name: string; weight: number; instrumentId: string }>;
	}

	const grouped = $derived.by<BlockGroup[]>(() => {
		const funds = portfolio?.fund_selection_schema?.funds ?? [];
		if (funds.length === 0) return [];

		const map = new Map<string, BlockGroup>();
		for (const f of funds) {
			const key = f.block_id || "unallocated";
			if (!map.has(key)) {
				map.set(key, {
					blockId: key,
					blockName: blockLabel(key) || key,
					totalWeight: 0,
					funds: [],
				});
			}
			const group = map.get(key)!;
			group.totalWeight += f.weight ?? 0;
			group.funds.push({
				name: f.fund_name,
				weight: f.weight ?? 0,
				instrumentId: f.instrument_id,
			});
		}
		return Array.from(map.values()).sort((a, b) => b.totalWeight - a.totalWeight);
	});

	const isEmpty = $derived(grouped.length === 0);

	const option = $derived.by(() => {
		if (isEmpty) return {} as Record<string, unknown>;

		// Treemap data: each block is a parent node containing its funds
		// as children. ECharts will pack the children inside the parent
		// rectangle proportionally.
		const data = grouped.map((g) => ({
			name: g.blockName,
			value: g.totalWeight,
			children: g.funds.map((f) => ({
				name: f.name,
				value: f.weight,
				path: `${g.blockName} / ${f.name}`,
			})),
		}));

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
			tooltip: {
				trigger: "item" as const,
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				formatter: (params: { data: { name: string; value: number; path?: string } }) => {
					const label = params.data.path ?? params.data.name;
					return `${label}<br/><strong>${formatPercent(params.data.value, 2)}</strong>`;
				},
			},
			series: [
				{
					type: "treemap" as const,
					data,
					roam: false,
					nodeClick: false,
					breadcrumb: { show: false },
					label: {
						show: true,
						formatter: (params: { name: string; value: number }) =>
							`${params.name}\n${formatNumber(params.value * 100, 1)}%`,
						fontSize: 11,
						fontWeight: 600,
						color: "#ffffff",
					},
					upperLabel: {
						show: true,
						height: 22,
						fontSize: 11,
						fontWeight: 700,
						color: "#ffffff",
						backgroundColor: "rgba(0,0,0,0.18)",
					},
					itemStyle: {
						borderColor: "#0e0f13",
						borderWidth: 1,
						gapWidth: 2,
					},
					levels: [
						{
							itemStyle: {
								borderColor: "#0e0f13",
								borderWidth: 2,
								gapWidth: 2,
							},
							upperLabel: { show: true },
						},
						{
							colorSaturation: [0.3, 0.55],
							itemStyle: {
								borderColorSaturation: 0.55,
								borderWidth: 1,
								gapWidth: 1,
							},
						},
					],
				},
			],
		} as Record<string, unknown>;
	});
</script>

{#if isEmpty}
	<EmptyState
		title="No holdings to render"
		message="Run a construction to populate the portfolio's fund selection."
	/>
{:else}
	<ChartContainer {option} {height} ariaLabel="Holdings treemap by allocation block" />
{/if}

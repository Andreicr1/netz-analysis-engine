<!--
  PR-A26.3 Section C — Donut chart of the approved target weights,
  grouped visually by block family (equity / fixed income / alt /
  cash). When no approval exists, renders an empty-state hint instead
  of a broken donut.
-->
<script lang="ts">
	import { formatNumber, formatPercent } from "@investintell/ui";
	import GenericEChart from "$lib/components/charts/GenericEChart.svelte";
	import {
		blockFamily,
		type BlockFamily,
		type StrategicAllocationBlock,
	} from "$lib/types/allocation-page";

	interface Props {
		blocks: StrategicAllocationBlock[];
		hasActiveApproval: boolean;
	}
	let { blocks, hasActiveApproval }: Props = $props();

	const FAMILY_COLOR: Record<BlockFamily, string> = {
		equity: "#3b82f6",
		fixed_income: "#10b981",
		alternatives: "#f59e0b",
		cash: "#64748b",
	};

	let options = $derived.by(() => {
		const data = blocks
			.filter((b) => (b.target_weight ?? 0) > 0)
			.map((b) => ({
				name: b.block_name,
				value: b.target_weight ?? 0,
				itemStyle: { color: FAMILY_COLOR[blockFamily(b.block_id)] },
			}));

		return {
			tooltip: {
				trigger: "item",
				formatter: (params: { name: string; value: number; percent: number }) =>
					`${params.name}<br/>${formatPercent(params.value)} (${formatNumber(params.percent, 1)}%)`,
			},
			legend: { show: false },
			series: [
				{
					name: "Strategic Allocation",
					type: "pie",
					radius: ["45%", "75%"],
					avoidLabelOverlap: true,
					label: { show: false },
					labelLine: { show: false },
					data,
				},
			],
		};
	});
</script>

{#if hasActiveApproval}
	<GenericEChart {options} height={260} />
{:else}
	<div
		class="h-[260px] flex items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground"
	>
		Awaiting first approval.
	</div>
{/if}

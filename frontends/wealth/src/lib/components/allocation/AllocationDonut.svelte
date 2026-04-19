<!--
  PR-A26.3 Section C — Donut chart of the approved target weights,
  grouped visually by block family (equity / fixed income / alt /
  cash). When no approval exists, renders an empty-state hint instead
  of a broken donut.

  PR-4b — family colors resolved via readTerminalTokens() dataviz
  palette; empty-state re-skinned with terminal tokens.
-->
<script lang="ts">
	import {
		formatNumber,
		formatPercent,
		readTerminalTokens,
	} from "@investintell/ui";
	import GenericEChart from "$wealth/components/charts/GenericEChart.svelte";
	import {
		blockFamily,
		type BlockFamily,
		type StrategicAllocationBlock,
	} from "$wealth/types/allocation-page";

	interface Props {
		blocks: StrategicAllocationBlock[];
		hasActiveApproval: boolean;
	}
	let { blocks, hasActiveApproval }: Props = $props();

	let options = $derived.by(() => {
		const tokens = readTerminalTokens();
		// Pull family colors from the terminal dataviz palette so the
		// donut inherits the same colorblind-safe ordering used by the
		// rest of the terminal surface (tokens.dataviz is 8 slots).
		const familyColor: Record<BlockFamily, string> = {
			equity: tokens.dataviz[6] ?? tokens.accentCyan, // cobalt
			fixed_income: tokens.statusSuccess, // success green
			alternatives: tokens.accentAmber, // amber
			cash: tokens.fgTertiary, // muted grey
		};

		const data = blocks
			.filter((b) => (b.target_weight ?? 0) > 0)
			.map((b) => ({
				name: b.block_name,
				value: b.target_weight ?? 0,
				itemStyle: { color: familyColor[blockFamily(b.block_id)] },
			}));

		return {
			tooltip: {
				trigger: "item",
				formatter: (params: {
					name: string;
					value: number;
					percent: number;
				}) =>
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
	<div class="empty-state">Awaiting first approval.</div>
{/if}

<style>
	.empty-state {
		height: 260px;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px dashed var(--terminal-fg-muted);
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-tertiary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
</style>

<!--
  PR-A26.3 Section C — Strategic Allocation table.

  18 rows × 5 cols per feedback_datagrid_vs_viewer (4-6 cols max). Row
  clicks are inert (no drill-down in v1); Edit Override emits an event
  the page handler wires to the modal.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { Pencil } from "lucide-svelte";
	import type { StrategicAllocationBlock } from "$lib/types/allocation-page";

	interface Props {
		blocks: StrategicAllocationBlock[];
		onEditOverride: (block: StrategicAllocationBlock) => void;
	}
	let { blocks, onEditOverride }: Props = $props();

	function rangeLabel(lo: number | null, hi: number | null): string {
		if (lo === null && hi === null) return "—";
		const lStr = lo !== null ? formatPercent(lo) : "—";
		const hStr = hi !== null ? formatPercent(hi) : "—";
		return `${lStr} – ${hStr}`;
	}
</script>

<div class="overflow-x-auto rounded-md border border-border">
	<table class="w-full text-sm">
		<thead class="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
			<tr>
				<th class="text-left px-3 py-2 font-medium">Asset Class</th>
				<th class="text-right px-3 py-2 font-medium">
					<span title="Approved target weight from last IPS approval.">Target</span>
				</th>
				<th class="text-right px-3 py-2 font-medium">
					<span title="Tolerance before rebalance triggers.">Drift Band</span>
				</th>
				<th class="text-right px-3 py-2 font-medium">
					<span title="Operator-set constraint for the next proposal.">Override</span>
				</th>
				<th class="text-right px-3 py-2 font-medium">Actions</th>
			</tr>
		</thead>
		<tbody>
			{#each blocks as block (block.block_id)}
				<tr
					class="border-t border-border"
					class:opacity-50={block.excluded_from_portfolio}
				>
					<td class="px-3 py-2 text-foreground">
						<div class="flex items-center gap-2">
							<span>{block.block_name}</span>
							{#if block.excluded_from_portfolio}
								<span
									class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground uppercase tracking-wider"
								>
									Excluded
								</span>
							{/if}
						</div>
					</td>
					<td class="px-3 py-2 text-right tabular-nums text-foreground">
						{block.target_weight !== null ? formatPercent(block.target_weight) : "—"}
					</td>
					<td class="px-3 py-2 text-right tabular-nums text-muted-foreground">
						{rangeLabel(block.drift_min, block.drift_max)}
					</td>
					<td class="px-3 py-2 text-right tabular-nums text-muted-foreground">
						{rangeLabel(block.override_min, block.override_max)}
					</td>
					<td class="px-3 py-2 text-right">
						<button
							type="button"
							onclick={() => onEditOverride(block)}
							class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-primary hover:bg-accent/40"
							title="Edit override for this block"
							aria-label="Edit override for {block.block_name}"
						>
							<Pencil class="w-3 h-3" />
							<span>Edit</span>
						</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<!--
  PR-A26.3 Section C — Strategic Allocation table.

  18 rows × 5 cols per feedback_datagrid_vs_viewer (4-6 cols max). Row
  clicks are inert (no drill-down in v1); Edit Override emits an event
  the page handler wires to the modal.

  PR-4b — terminal-density re-skin. All colors pulled from
  ``--terminal-*`` custom properties; row heights respect
  ``[data-density]`` via ``--t-row-height``. No cursor:pointer on
  data cells (§G.BUILDER.3) — only the Edit affordance is interactive.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { Pencil } from "lucide-svelte";
	import type { StrategicAllocationBlock } from "../../types/allocation-page";

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

<div class="strategic-allocation">
	<table>
		<thead>
			<tr>
				<th class="align-left">Asset Class</th>
				<th class="align-right">
					<span title="Approved target weight from last IPS approval.">Target</span>
				</th>
				<th class="align-right">
					<span title="Tolerance before rebalance triggers.">Drift Band</span>
				</th>
				<th class="align-right">
					<span title="Operator-set constraint for the next proposal.">Override</span>
				</th>
				<th class="align-right">Actions</th>
			</tr>
		</thead>
		<tbody>
			{#each blocks as block (block.block_id)}
				<tr class:excluded={block.excluded_from_portfolio}>
					<td class="align-left name">
						<div class="name-cell">
							<span>{block.block_name}</span>
							{#if block.excluded_from_portfolio}
								<span class="excluded-pill">Excluded</span>
							{/if}
						</div>
					</td>
					<td class="align-right numeric">
						{block.target_weight !== null
							? formatPercent(block.target_weight)
							: "—"}
					</td>
					<td class="align-right numeric muted">
						{rangeLabel(block.drift_min, block.drift_max)}
					</td>
					<td class="align-right numeric muted">
						{rangeLabel(block.override_min, block.override_max)}
					</td>
					<td class="align-right">
						<button
							type="button"
							class="edit-btn"
							onclick={() => onEditOverride(block)}
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

<style>
	.strategic-allocation {
		overflow-x: auto;
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-12);
	}
	thead tr {
		background: var(--terminal-bg-panel-sunken);
	}
	thead th {
		padding: var(--terminal-space-2) var(--terminal-space-3);
		font-weight: 500;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.align-left {
		text-align: left;
	}
	.align-right {
		text-align: right;
	}
	tbody tr {
		border-top: var(--terminal-border-hairline);
		height: var(--t-row-height);
	}
	tbody tr.excluded {
		opacity: 0.5;
	}
	tbody td {
		padding: var(--terminal-space-2) var(--terminal-space-3);
		color: var(--terminal-fg-primary);
		line-height: var(--terminal-leading-tight);
	}
	.numeric {
		font-variant-numeric: tabular-nums;
	}
	.muted {
		color: var(--terminal-fg-tertiary);
	}
	.name-cell {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}
	.excluded-pill {
		font-size: var(--terminal-text-10);
		padding: 0 var(--terminal-space-2);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.edit-btn {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border: var(--terminal-border-hairline);
		background: transparent;
		color: var(--terminal-accent-amber);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition: border-color var(--terminal-motion-tick)
			var(--terminal-motion-easing-out);
	}
	.edit-btn:hover,
	.edit-btn:focus-visible {
		border-color: var(--terminal-accent-amber);
		outline: none;
	}
</style>

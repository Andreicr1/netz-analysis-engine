<!--
  PortfolioOverview — Fund Selection grouped by allocation block with HTML5 DnD drop zones.
  Drag funds from UniversePanel; valid blocks accept, mismatched blocks reject visually.
-->
<script lang="ts">
	import { EmptyState, formatPercent } from "@investintell/ui";
	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";
	import { blockLabel } from "$lib/constants/blocks";
	import Target from "lucide-svelte/icons/target";

	// ── Drop zone visual state per block ────────────────────────────────
	let dropState = $state<Record<string, "idle" | "accept" | "reject">>({});

	function getDragFund(e: DragEvent): UniverseFund | null {
		const instrumentId = e.dataTransfer?.getData("text/plain");
		if (!instrumentId) return null;
		return workspace.universe.find((f) => f.instrument_id === instrumentId) ?? null;
	}

	function handleDragOver(e: DragEvent, blockId: string) {
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
	}

	function handleDragEnter(e: DragEvent, blockId: string) {
		e.preventDefault();
		// We can't read data on dragenter (security), so show neutral accept state
		// The actual validation happens on drop
		dropState[blockId] = "accept";
	}

	function handleDragLeave(e: DragEvent, blockId: string) {
		// Only reset if leaving the drop zone itself, not a child
		const target = e.currentTarget as HTMLElement;
		const related = e.relatedTarget as HTMLElement | null;
		if (related && target.contains(related)) return;
		dropState[blockId] = "idle";
	}

	function handleDrop(e: DragEvent, blockId: string) {
		e.preventDefault();
		const fund = getDragFund(e);
		if (!fund) {
			dropState[blockId] = "idle";
			return;
		}
		const accepted = workspace.addFundToBlock(fund, blockId);
		dropState[blockId] = accepted ? "idle" : "reject";
		if (!accepted) {
			// Flash reject state briefly
			setTimeout(() => { dropState[blockId] = "idle"; }, 600);
		}
	}

	// ── Blocks to display: existing + all universe blocks for empty drops ──
	let displayBlocks = $derived.by(() => {
		const blocks = new Set<string>();
		for (const f of workspace.funds) blocks.add(f.block_id);
		for (const f of workspace.universe) blocks.add(f.block_id);
		return [...blocks];
	});
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio from the sidebar to view its fund allocation."
		/>
	</div>
{:else}
	<div class="overview-panel">
		<div class="overview-header">
			<Target class="h-4 w-4" style="color: var(--ii-chart-1, #0177fb);" />
			<span class="overview-title">Fund Selection</span>
			<span class="overview-subtitle">
				{workspace.funds.length} fund{workspace.funds.length !== 1 ? "s" : ""} allocated
			</span>
		</div>

		<div class="blocks-grid">
			{#each displayBlocks as blockId (blockId)}
				{@const blockFunds = workspace.fundsByBlock[blockId] ?? []}
				{@const state = dropState[blockId] ?? "idle"}
				<div
					class="block-card"
					class:block-accept={state === "accept"}
					class:block-reject={state === "reject"}
					role="region"
					aria-label="{blockLabel(blockId)} allocation block"
					ondragover={(e) => handleDragOver(e, blockId)}
					ondragenter={(e) => handleDragEnter(e, blockId)}
					ondragleave={(e) => handleDragLeave(e, blockId)}
					ondrop={(e) => handleDrop(e, blockId)}
				>
					<div class="block-header">
						<span class="block-label">{blockLabel(blockId)}</span>
						{#if blockFunds.length > 0}
							<span class="block-weight">
								{formatPercent(blockFunds.reduce((s: number, f: { weight: number }) => s + f.weight, 0))}
							</span>
						{/if}
					</div>

					{#if blockFunds.length === 0}
						<div class="block-empty">
							<span class="block-empty-text">Drop funds here</span>
						</div>
					{:else}
						<table class="fund-table">
							<tbody>
								{#each blockFunds as fund (fund.instrument_id)}
									<tr class="fund-row">
										<td class="td-name">
											<span class="fund-name">{fund.fund_name}</span>
											{#if fund.instrument_type}
												<span class="fund-type-badge">{fund.instrument_type.replace(/_/g, " ")}</span>
											{/if}
										</td>
										<td class="td-score">{fund.score?.toFixed(1) ?? "—"}</td>
										<td class="td-weight">{formatPercent(fund.weight)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				</div>
			{/each}
		</div>

		{#if workspace.funds.length > 0}
			<div class="total-strip">
				<span class="total-label">{workspace.funds.length} funds total</span>
				<span class="total-weight">
					{formatPercent(workspace.funds.reduce((s: number, f: { weight: number }) => s + f.weight, 0))}
				</span>
			</div>
		{/if}
	</div>
{/if}

<style>
	.overview-panel {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 16px;
		height: 100%;
	}

	.overview-header {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.overview-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.overview-subtitle {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		margin-left: auto;
	}

	.blocks-grid {
		display: flex;
		flex-direction: column;
		gap: 8px;
		flex: 1;
		overflow-y: auto;
		min-height: 0;
	}

	.block-card {
		border: 1.5px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 9px);
		background: var(--ii-surface);
		transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;
	}

	.block-accept {
		border-color: var(--ii-success, #11ec79);
		border-style: dashed;
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-success, #11ec79) 20%, transparent);
		background: color-mix(in srgb, var(--ii-success, #11ec79) 4%, var(--ii-surface));
	}

	.block-reject {
		border-color: var(--ii-danger, #fc1a1a);
		border-style: dashed;
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-danger, #fc1a1a) 20%, transparent);
		background: color-mix(in srgb, var(--ii-danger, #fc1a1a) 4%, var(--ii-surface));
	}

	.block-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.block-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.block-weight {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.block-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 16px;
	}

	.block-empty-text {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		opacity: 0.6;
	}

	.fund-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
		font-variant-numeric: tabular-nums;
	}

	.fund-row {
		transition: background 100ms ease;
	}

	.fund-row:hover {
		background: var(--ii-surface-alt);
	}

	.fund-row td {
		padding: 6px 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-primary);
	}

	.fund-row:last-child td {
		border-bottom: none;
	}

	.td-name {
		min-width: 140px;
	}

	.td-score,
	.td-weight {
		text-align: right;
		white-space: nowrap;
		font-weight: 600;
		width: 70px;
	}

	.fund-name {
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.fund-type-badge {
		display: inline-block;
		margin-left: 6px;
		padding: 1px 6px;
		border-radius: var(--ii-radius-sm, 4px);
		background: var(--ii-surface-alt);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		text-transform: capitalize;
		vertical-align: middle;
	}

	.total-strip {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px;
		background: var(--ii-surface-alt);
		border-radius: var(--ii-radius-md, 9px);
	}

	.total-label {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-muted);
	}

	.total-weight {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}
</style>

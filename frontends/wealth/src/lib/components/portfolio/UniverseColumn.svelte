<!--
  UniverseColumn — Wrapper for the Approved Universe column in the
  Portfolio Builder Flexible Columns Layout.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §1.2

  Owns:
    - Header with search, count, and (future) asset class / region /
      liquidity filter pills.
    - <svelte:boundary> around the UniverseTable with `failed` snippet
      showing PanelErrorState — if the table crashes mid-render, the
      Builder column keeps working.
    - Debounced text search with in-memory state (no localStorage).

  Delegates to:
    - UniverseTable for the 12-column densa rendering.
    - `workspace.loadUniverse()` for data loading (triggered by the
      orchestrator's `$effect`).
    - `onSelectFund` callback to open the Analytics column.
-->
<script lang="ts">
	import Loader2 from "lucide-svelte/icons/loader-2";
	import Undo2 from "lucide-svelte/icons/undo-2";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";
	import UniverseTable from "./UniverseTable.svelte";

	interface Props {
		onSelectFund: (fund: UniverseFund) => void;
	}

	let { onSelectFund }: Props = $props();

	// Full universe passed straight to the table — no client-side
	// filtering while the header search bar is suspended. When search
	// returns (as a sub-pill toolbar feature), this becomes a $derived
	// over workspace.universe again.
	const filtered = $derived(workspace.universe);

	// ── Drop target for reverse drag-drop ────────────────────────
	// The Portfolio Builder is a staging area: funds dragged OUT of
	// the Builder blocks and dropped here are REMOVED from the
	// allocation. The payload signature is the same text/plain
	// instrument_id, but with an extra "application/x-netz-allocated"
	// MIME type set by PortfolioOverview so we know this is a
	// removal intent (not a duplicate add). Simple drops of Universe
	// fund IDs onto the Universe itself are no-ops (they come from
	// allocated blocks only in practice).
	let removeDropActive = $state(false);

	function isAllocatedDrag(e: DragEvent): boolean {
		if (!e.dataTransfer) return false;
		return e.dataTransfer.types.includes("application/x-netz-allocated");
	}

	function handleRemoveDragOver(e: DragEvent) {
		if (!isAllocatedDrag(e)) return;
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
		removeDropActive = true;
	}

	function handleRemoveDragLeave(e: DragEvent) {
		const related = e.relatedTarget as Node | null;
		const current = e.currentTarget as HTMLElement;
		if (related && current.contains(related)) return;
		removeDropActive = false;
	}

	function handleRemoveDrop(e: DragEvent) {
		if (!isAllocatedDrag(e)) return;
		e.preventDefault();
		const instrumentId = e.dataTransfer?.getData("text/plain");
		removeDropActive = false;
		if (!instrumentId) return;
		workspace.removeFund(instrumentId);
	}
</script>

<div
	class="uc-root"
	class:uc-root--removing={removeDropActive}
	ondragover={handleRemoveDragOver}
	ondragleave={handleRemoveDragLeave}
	ondrop={handleRemoveDrop}
	role="region"
	aria-label="Approved Universe — drop allocated funds here to remove them from the Builder"
>
	{#if removeDropActive}
		<div class="uc-remove-overlay">
			<Undo2 size={28} />
			<span class="uc-remove-title">Drop to return fund to the Universe</span>
			<span class="uc-remove-sub">The portfolio is not live — changes are staged for review</span>
		</div>
	{/if}

	<!--
	  Header removed 2026-04-08 per visual alignment feedback: the
	  Builder column does not carry an equivalent chrome, so the
	  "Approved Universe" label + count + search-bar row was breaking
	  Y-axis alignment between the two table <thead>s.

	  The <UniverseTable> thead starts directly at the top of the
	  column now, matching BuilderTable. Search functionality is
	  temporarily suspended — when it returns it will live inside
	  the sub-pills toolbar (Models | Universe | Policy) in the
	  left shell, not inside this column.
	-->

	<svelte:boundary>
		<div class="uc-body">
			{#if workspace.isLoadingUniverse && workspace.universe.length === 0}
				<div class="uc-loading">
					<Loader2 size={16} class="uc-spinner" />
					<span>Loading approved universe…</span>
				</div>
			{:else}
				<UniverseTable funds={filtered} {onSelectFund} />
			{/if}
		</div>

		{#snippet failed(error: unknown, reset: () => void)}
			<PanelErrorState
				title="Universe table failed to render"
				message={error instanceof Error ? error.message : "Unexpected error in the approved universe."}
				onRetry={reset}
			/>
		{/snippet}
	</svelte:boundary>
</div>

<style>
	/* Hardcoded dark — no var() fallbacks. Matches legacy UniversePanel. */
	.uc-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
		overflow: hidden;
		position: relative;
		transition: box-shadow 120ms ease, background 120ms ease;
	}

	/* ── Drop target highlight: fund being dragged BACK out of the
	 *    Builder. Inner shadow + subtle brand tint signal "release
	 *    here to remove from allocation". The removal is reversible
	 *    — the portfolio is a staging area, not live. */
	.uc-root--removing {
		background: rgba(1, 119, 251, 0.04);
		box-shadow: inset 0 0 0 2px rgba(1, 119, 251, 0.45);
	}

	.uc-remove-overlay {
		position: absolute;
		inset: 0;
		background: rgba(14, 15, 19, 0.82);
		backdrop-filter: blur(2px);
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		z-index: 5;
		pointer-events: none;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
	}

	.uc-remove-title {
		font-size: 15px;
		font-weight: 600;
		color: #ffffff;
	}

	.uc-remove-sub {
		font-size: 12px;
		font-weight: 400;
		color: #85a0bd;
		font-style: italic;
	}

	/* Header styles removed 2026-04-08 along with the <header> element.
	 * The table now starts at the top of the column, mirroring the
	 * Builder column structure. If the search returns, it will live
	 * as a toolbar inside the left-shell sub-pills row, not here. */

	.uc-body {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	.uc-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 48px 16px;
		color: #85a0bd;
		font-size: 0.8125rem;
	}

	.uc-loading :global(.uc-spinner) {
		animation: uc-spin 1s linear infinite;
	}

	@keyframes uc-spin {
		to { transform: rotate(360deg); }
	}
</style>

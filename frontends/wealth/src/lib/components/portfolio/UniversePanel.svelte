<!--
  UniversePanel — Draggable fund cards from the approved universe.
  Drag funds into PortfolioOverview drop zones to add them to allocation blocks.
  Search bar filters by fund name, ticker, or block label.
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import GripVertical from "lucide-svelte/icons/grip-vertical";
	import Search from "lucide-svelte/icons/search";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { Badge } from "@investintell/ui/components/ui/badge";
	import { Input } from "@investintell/ui/components/ui/input";
	import { createDebouncedState } from "$lib/utils/reactivity";

	const search = createDebouncedState("", 300);

	/** Reactive filtered list — depends on debounced value for 60fps typing. */
	let filteredUniverse = $derived.by(() => {
		const term = search.debounced.trim().toLowerCase();
		if (!term) return workspace.universe;
		return workspace.universe.filter((f) => f._searchKey.includes(term));
	});

	function handleDragStart(e: DragEvent, fund: typeof workspace.universe[0]) {
		if (!e.dataTransfer) return;
		e.dataTransfer.effectAllowed = "copy";
		e.dataTransfer.setData("text/plain", fund.instrument_id);
	}

	/** Check if fund is already in the portfolio */
	function isAllocated(instrumentId: string): boolean {
		return workspace.funds.some((f: any) => f.instrument_id === instrumentId);
	}
</script>

<div class="universe-panel">
	<div class="universe-header">
		<span class="universe-title">Available Funds</span>
		<span class="universe-count">
			{#if search.current}
				{filteredUniverse.length} / {workspace.universe.length}
			{:else}
				{workspace.universe.length}
			{/if}
		</span>
	</div>

	<!-- Search bar -->
	<div class="universe-search">
		<Search class="h-3.5 w-3.5" style="color: var(--ii-text-muted); flex-shrink: 0;" />
		<Input
			type="text"
			placeholder="Search by name, ticker, or block…"
			value={search.current}
			oninput={(e: Event) => { search.current = (e.target as HTMLInputElement).value; }}
			onkeydown={(e: KeyboardEvent) => { if (e.key === "Enter") search.flush(); }}
			class="search-input"
		/>
	</div>

	{#if workspace.isLoadingUniverse}
		<div class="universe-loading">
			<Loader2 class="h-5 w-5 animate-spin" style="color: var(--ii-text-muted);" />
			<span>Loading universe…</span>
		</div>
	{:else if filteredUniverse.length === 0}
		<div class="universe-loading">
			<span>{search.current ? "No funds match your search." : "No approved funds in universe."}</span>
		</div>
	{:else}
		<div class="universe-list">
			{#each filteredUniverse as fund (fund.instrument_id)}
				{@const allocated = isAllocated(fund.instrument_id)}
				<div
					class="universe-card"
					class:universe-card--allocated={allocated}
					draggable={!allocated}
					ondragstart={(e) => handleDragStart(e, fund)}
					role="listitem"
				>
					<div class="card-grip" class:grip-disabled={allocated}>
						<GripVertical class="h-3.5 w-3.5" />
					</div>
					<div class="card-info">
						<span class="card-name">
							{fund.fund_name}
							{#if fund.ticker}
								<span class="card-ticker">{fund.ticker}</span>
							{/if}
						</span>
						<span class="card-block">{fund.block_label}</span>
					</div>
					{#if allocated}
						<Badge variant="secondary" class="card-badge">Added</Badge>
					{:else}
						<Badge variant="outline" class="card-badge">{fund.instrument_type.replace(/_/g, " ")}</Badge>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.universe-panel {
		display: flex;
		flex-direction: column;
		height: 100%;
	}

	.universe-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.universe-title {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.universe-count {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		background: var(--ii-surface-alt);
		padding: 1px 8px;
		border-radius: var(--ii-radius-sm, 4px);
		font-variant-numeric: tabular-nums;
	}

	.universe-search {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.universe-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 32px 16px;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.universe-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 8px;
		flex: 1;
		overflow-y: auto;
	}

	.universe-card {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 10px;
		border-radius: var(--ii-radius-md, 9px);
		border: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface);
		cursor: grab;
		transition: border-color 120ms ease, box-shadow 120ms ease;
	}

	.universe-card:hover:not(.universe-card--allocated) {
		border-color: var(--ii-chart-1, #0177fb);
		box-shadow: 0 0 0 1px var(--ii-chart-1, #0177fb);
	}

	.universe-card:active:not(.universe-card--allocated) {
		cursor: grabbing;
	}

	.universe-card--allocated {
		opacity: 0.5;
		cursor: default;
		border-style: dashed;
	}

	.card-grip {
		color: var(--ii-text-muted);
		flex-shrink: 0;
	}

	.grip-disabled {
		opacity: 0.3;
	}

	.card-info {
		display: flex;
		flex-direction: column;
		gap: 1px;
		flex: 1;
		min-width: 0;
	}

	.card-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.card-ticker {
		font-weight: 500;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
		margin-left: 4px;
	}

	.card-block {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}
</style>

<!--
  UniversePanel — Analytical data table of approved universe funds.
  Draggable rows into PortfolioOverview drop zones.
  Columns: Grip | Fund (name+ticker) | Score | Block | Class | Geo | Action
  Design: Figma One X dark premium data table.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";
	import { blockDisplay, BLOCK_GROUPS, groupDisplay } from "$wealth/constants/blocks";
	import GripVertical from "lucide-svelte/icons/grip-vertical";
	import Search from "lucide-svelte/icons/search";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import ExternalLink from "lucide-svelte/icons/external-link";
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import { createDebouncedState } from "$wealth/utils/reactivity";

	const search = createDebouncedState("", 300);

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

	function isAllocated(instrumentId: string): boolean {
		return workspace.funds.some((f: any) => f.instrument_id === instrumentId);
	}

	function openFactSheet(instrumentId: string) {
		goto(`/screener/fund/${instrumentId}`);
	}

	/** UX Glossary: format raw asset_class for display */
	function formatAssetClass(raw: string | null): string {
		if (!raw) return "—";
		return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	/** UX Glossary: format raw geography for display */
	function formatGeo(raw: string | null): string {
		if (!raw) return "—";
		return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	const GROUP_ORDER = ["CASH & EQUIVALENTS", "EQUITIES", "FIXED INCOME", "ALTERNATIVES"];

	let universeTree = $derived.by(() => {
		const groupMap = new Map<string, typeof workspace.universe>();

		// Helper to find the group name for a block_id
		function getGroupName(blockId: string): string {
			for (const [groupName, blocks] of Object.entries(BLOCK_GROUPS)) {
				if (blocks.includes(blockId)) return groupName;
			}
			return "OTHER";
		}

		for (const fund of filteredUniverse) {
			const groupName = getGroupName(fund.block_id);
			if (!groupMap.has(groupName)) groupMap.set(groupName, []);
			groupMap.get(groupName)!.push(fund);
		}

		const result = [];
		for (const key of GROUP_ORDER) {
			const funds = groupMap.get(key);
			if (funds && funds.length > 0) {
				result.push({ name: key, displayName: groupDisplay(key), funds });
				groupMap.delete(key);
			}
		}
		for (const [key, funds] of groupMap.entries()) {
			if (funds.length > 0) {
				result.push({ name: key, displayName: groupDisplay(key), funds });
			}
		}
		return result;
	});

	let collapsed = $state<Record<string, boolean>>({});

	function toggleGroup(group: string) {
		collapsed[group] = !collapsed[group];
	}
</script>

<div class="flex flex-col h-full">
	<!-- Header -->
	<div class="flex items-center justify-between px-4 py-2.5 shrink-0" style="border-bottom: 1px solid #404249;">
		<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em]">Approved Universe</span>
		<span class="text-[11px] font-bold text-white bg-white/5 px-2 py-0.5 rounded-full tabular-nums">
			{#if search.current}
				{filteredUniverse.length} / {workspace.universe.length}
			{:else}
				{workspace.universe.length}
			{/if}
		</span>
	</div>

	<!-- Search bar -->
	<div class="flex items-center gap-2 px-4 py-2 shrink-0" style="border-bottom: 1px solid #404249;">
		<Search class="h-3 w-3 text-[#85a0bd] shrink-0" />
		<input
			type="text"
			placeholder="Search name, ticker, block…"
			value={search.current}
			oninput={(e) => { search.current = (e.target as HTMLInputElement).value; }}
			onkeydown={(e) => { if (e.key === "Enter") search.flush(); }}
			class="flex-1 min-w-0 bg-transparent border-none outline-none text-[12px] text-white placeholder:text-[#85a0bd]/50"
			style="font-family: var(--ii-font-sans);"
		/>
	</div>

	{#if workspace.isLoadingUniverse}
		<div class="flex items-center justify-center gap-2 py-10 text-[#85a0bd] text-[13px]">
			<Loader2 class="h-5 w-5 animate-spin text-[#85a0bd]" />
			<span>Loading universe…</span>
		</div>
	{:else if filteredUniverse.length === 0}
		<div class="flex items-center justify-center py-10 text-[#85a0bd] text-[12px]">
			<span>{search.current ? "No funds match." : "No approved funds."}</span>
		</div>
	{:else}
		<!-- Column headers -->
		<div class="grid grid-cols-[16px_1fr_40px_minmax(110px,1.2fr)_65px_65px_24px] gap-1 px-3 py-1.5 shrink-0 text-[10px] font-semibold text-[#85a0bd]/60 uppercase tracking-[0.06em]" style="border-bottom: 1px solid rgba(64, 66, 73, 0.6);">
			<span></span>
			<span>Fund</span>
			<span class="text-right">Score</span>
			<span>Block</span>
			<span>Class</span>
			<span>Geo</span>
			<span></span>
		</div>

		<!-- Scrollable data rows -->
		<div class="flex-1 overflow-y-auto min-h-0 flex flex-col gap-1 py-1">
			{#each universeTree as group (group.name)}
				{@const isCollapsed = collapsed[group.name] ?? false}
				<div class="flex flex-col">
					<!-- Group Header -->
					<button
						type="button"
						class="flex items-center gap-2 px-3 py-1.5 hover:bg-white/[0.02] transition-colors text-left sticky top-0 bg-[#141519]/95 backdrop-blur-sm z-10"
						onclick={() => toggleGroup(group.name)}
					>
						<ChevronRight
							class="h-3 w-3 text-[#85a0bd]/50 transition-transform duration-200 shrink-0
								{isCollapsed ? '' : 'rotate-90'}"
						/>
						<span class="text-[11px] font-bold text-[#cbccd1] uppercase tracking-[0.06em]">{group.displayName}</span>
						<span class="text-[9px] text-[#85a0bd] bg-white/5 px-1.5 py-0.5 rounded-full tabular-nums ml-1">{group.funds.length}</span>
					</button>

					<!-- Group Funds -->
					{#if !isCollapsed}
						<div class="flex flex-col">
							{#each group.funds as fund (fund.instrument_id)}
								{@const allocated = isAllocated(fund.instrument_id)}
								<div
									class="grid grid-cols-[16px_1fr_40px_minmax(110px,1.2fr)_65px_65px_24px] gap-1 items-center px-3 py-1.5 transition-colors duration-100 group
										{allocated
											? 'opacity-35 cursor-default'
											: 'cursor-grab hover:bg-white/[0.03] active:cursor-grabbing'}"
									style="border-bottom: 1px solid rgba(64, 66, 73, 0.3);"
									draggable={!allocated}
									ondragstart={(e) => handleDragStart(e, fund)}
									role="listitem"
								>
									<!-- Grip -->
									<div class="text-[#85a0bd]/30 shrink-0" class:opacity-30={allocated}>
										<GripVertical class="h-3 w-3" />
									</div>

									<!-- Fund name + ticker -->
									<div class="flex flex-col min-w-0">
										<div class="flex items-center gap-1 min-w-0">
											<span class="text-[11px] font-semibold text-white truncate">{fund.fund_name}</span>
											{#if allocated}
												<span class="text-[8px] font-bold text-[#0177fb] bg-[#0177fb]/10 px-1 py-px rounded-full uppercase shrink-0">In</span>
											{/if}
										</div>
										{#if fund.ticker}
											<span class="text-[9px] text-[#85a0bd]/60 tabular-nums">{fund.ticker}</span>
										{/if}
									</div>

									<!-- Score (quant) -->
									<span class="text-[10px] font-semibold text-[#cbccd1] tabular-nums text-right">{fund.manager_score ?? "—"}</span>

									<!-- Block (allocation origin) -->
									<span class="text-[10px] text-[#85a0bd] truncate" title={blockDisplay(fund.block_id)}>
										{blockDisplay(fund.block_id)}
									</span>

									<!-- Asset Class -->
									<span class="text-[9px] text-[#85a0bd]/70 truncate" title={formatAssetClass(fund.asset_class)}>
										{formatAssetClass(fund.asset_class)}
									</span>

									<!-- Geography -->
									<span class="text-[9px] text-[#85a0bd]/70 truncate" title={formatGeo(fund.geography)}>
										{formatGeo(fund.geography)}
									</span>

									<!-- Deeplink to Fact Sheet -->
									<button
										type="button"
										class="flex items-center justify-center w-5 h-5 rounded text-[#85a0bd]/20 hover:text-[#0177fb] hover:bg-[#0177fb]/10 transition-colors opacity-0 group-hover:opacity-100"
										onclick={(e) => { e.stopPropagation(); openFactSheet(fund.instrument_id); }}
										title="Open Fund Fact Sheet"
									>
										<ExternalLink class="h-2.5 w-2.5" />
									</button>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

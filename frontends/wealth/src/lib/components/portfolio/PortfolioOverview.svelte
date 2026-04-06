<!--
  PortfolioOverview — 3-level allocation tree with DnD drop zones.
  Level 1: Asset Class group (collapsible accordion)
  Level 2: Block / Region (UX glossary mapped, drop target)
  Level 3: Fund cards
  Cash & Equivalents always renders first (Private Banking convention).
  All groups are collapsible smart accordions.
  Design: Figma One X dark premium, strong typographic hierarchy.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { EmptyState, formatPercent } from "@investintell/ui";
	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";
	import { blockLabel, BLOCK_GROUPS, blockDisplay, groupDisplay } from "$lib/constants/blocks";
	import Target from "lucide-svelte/icons/target";
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import Plus from "lucide-svelte/icons/plus";
	import ExternalLink from "lucide-svelte/icons/external-link";
	import GripVertical from "lucide-svelte/icons/grip-vertical";

	// ── Drop zone visual state per block ────────────────────────────────
	let dropState = $state<Record<string, "idle" | "accept" | "reject">>({});

	// ── Collapsed state per asset class group & block ─────────
	let collapsedGroup = $state<Record<string, boolean>>({});
	let collapsedBlock = $state<Record<string, boolean>>({});

	function toggleGroup(group: string) {
		collapsedGroup[group] = !collapsedGroup[group];
	}

	function toggleBlock(blockId: string, e: Event) {
		e.stopPropagation();
		collapsedBlock[blockId] = !collapsedBlock[blockId];
	}

	function getDragFund(e: DragEvent): UniverseFund | null {
		const instrumentId = e.dataTransfer?.getData("text/plain");
		if (!instrumentId) return null;
		return workspace.universe.find((f) => f.instrument_id === instrumentId) ?? null;
	}

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
	}

	function handleDragEnter(e: DragEvent, blockId: string) {
		e.preventDefault();
		dropState[blockId] = "accept";
	}

	function handleDragLeave(e: DragEvent, blockId: string) {
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
			setTimeout(() => { dropState[blockId] = "idle"; }, 600);
		} else {
			// Expand the block if it was collapsed and a fund was added
			collapsedBlock[blockId] = false;
		}
	}

	function openFactSheet(instrumentId: string, e: Event) {
		e.stopPropagation();
		goto(`/screener/fund/${instrumentId}`);
	}

	// ── Build 3-level tree from blocks ──────────────────────────────────

	let activeBlockIds = $derived.by(() => {
		const blocks = new Set<string>();
		for (const f of workspace.funds) blocks.add(f.block_id);
		for (const f of workspace.universe) blocks.add(f.block_id);
		return blocks;
	});

	interface TreeBlock {
		blockId: string;
		label: string;
		displayLabel: string;
		funds: any[];
		weight: number;
	}

	interface TreeGroup {
		name: string;
		displayName: string;
		blocks: TreeBlock[];
		totalWeight: number;
		fundCount: number;
	}

	/** Cash-first ordering: CASH & EQUIVALENTS always at index 0 */
	const GROUP_ORDER = ["CASH & EQUIVALENTS", "EQUITIES", "FIXED INCOME", "ALTERNATIVES"];

	let tree = $derived.by((): TreeGroup[] => {
		const groupMap = new Map<string, TreeGroup>();

		for (const [groupName, blockIds] of Object.entries(BLOCK_GROUPS)) {
			const blocks: TreeBlock[] = [];

			for (const blockId of blockIds) {
				if (!activeBlockIds.has(blockId)) continue;
				const funds = workspace.fundsByBlock[blockId] ?? [];
				const weight = funds.reduce((s: number, f: { weight: number }) => s + f.weight, 0);
				blocks.push({
					blockId,
					label: blockLabel(blockId),
					displayLabel: blockDisplay(blockId),
					funds,
					weight,
				});
			}

			if (blocks.length === 0) continue;

			const totalWeight = blocks.reduce((s, b) => s + b.weight, 0);
			const fundCount = blocks.reduce((s, b) => s + b.funds.length, 0);
			groupMap.set(groupName, {
				name: groupName,
				displayName: groupDisplay(groupName),
				blocks,
				totalWeight,
				fundCount,
			});
		}

		// Catch unmapped blocks
		const mapped = new Set(Object.values(BLOCK_GROUPS).flat());
		const unmapped: TreeBlock[] = [];
		for (const blockId of activeBlockIds) {
			if (mapped.has(blockId)) continue;
			const funds = workspace.fundsByBlock[blockId] ?? [];
			const weight = funds.reduce((s: number, f: { weight: number }) => s + f.weight, 0);
			unmapped.push({
				blockId,
				label: blockLabel(blockId),
				displayLabel: blockDisplay(blockId),
				funds,
				weight,
			});
		}
		if (unmapped.length > 0) {
			groupMap.set("OTHER", {
				name: "OTHER",
				displayName: groupDisplay("OTHER"),
				blocks: unmapped,
				totalWeight: unmapped.reduce((s, b) => s + b.weight, 0),
				fundCount: unmapped.reduce((s, b) => s + b.funds.length, 0),
			});
		}

		// Sort: Cash first, then defined order, then anything else
		const result: TreeGroup[] = [];
		for (const key of GROUP_ORDER) {
			const g = groupMap.get(key);
			if (g) {
				result.push(g);
				groupMap.delete(key);
			}
		}
		// Append any remaining (OTHER, etc.)
		for (const g of groupMap.values()) {
			result.push(g);
		}

		return result;
	});

	function formatAssetClass(raw: string | null): string {
		if (!raw) return "—";
		return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	function formatGeo(raw: string | null): string {
		if (!raw) return "—";
		return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio from the sidebar to view its fund allocation."
		/>
	</div>
{:else}
	<div class="flex flex-col gap-3 p-5 flex-1 min-h-min">
		<!-- Header -->
		<div class="flex items-center gap-2 shrink-0">
			<Target class="h-4 w-4 text-[#0177fb]" />
			<span class="text-[15px] font-bold text-white">Fund Selection</span>
			<span class="text-[12px] text-[#85a0bd] ml-auto">
				{workspace.funds.length} fund{workspace.funds.length !== 1 ? "s" : ""} allocated
			</span>
		</div>

		<!-- Table Headers -->
		<div class="grid grid-cols-[16px_1fr_40px_minmax(110px,1.2fr)_65px_65px_60px_24px] gap-1 px-4 py-2 mt-2 shrink-0 text-[10px] font-semibold text-[#85a0bd]/60 uppercase tracking-[0.06em]" style="border-bottom: 1px solid rgba(64, 66, 73, 0.6);">
			<span></span>
			<span>Fund</span>
			<span class="text-right">Score</span>
			<span>Block</span>
			<span>Class</span>
			<span>Geo</span>
			<span class="text-right">Weight</span>
			<span></span>
		</div>

		<!-- 3-Level Tree -->
		<div class="flex flex-col gap-2.5 min-h-min">
			{#each tree as group (group.name)}
				{@const isGroupCollapsed = collapsedGroup[group.name] ?? false}

				<!-- ══ Level 1: Asset Class Group (collapsible accordion) ══ -->
				<div class="rounded-[16px] bg-white/[0.015] border border-[#404249]/25 overflow-hidden">
					<button
						type="button"
						class="flex items-center gap-3 w-full px-5 py-3 hover:bg-white/[0.02] transition-colors text-left"
						onclick={() => toggleGroup(group.name)}
					>
						<ChevronRight
							class="h-4 w-4 text-[#85a0bd]/50 transition-transform duration-200 shrink-0
								{isGroupCollapsed ? '' : 'rotate-90'}"
						/>
						<span class="text-[13px] font-semibold text-[#cbccd1] uppercase tracking-[0.08em]">{group.displayName}</span>
						{#if group.fundCount > 0}
							<span class="text-[10px] text-[#85a0bd] bg-white/5 px-2 py-0.5 rounded-full tabular-nums">{group.fundCount}</span>
						{/if}
						<span class="ml-auto text-[13px] font-bold text-white tabular-nums">
							{group.totalWeight > 0 ? formatPercent(group.totalWeight) : ""}
						</span>
					</button>

					{#if !isGroupCollapsed}
						<div class="flex flex-col px-1 pb-2">
							{#each group.blocks as block (block.blockId)}
								{@const state = dropState[block.blockId] ?? "idle"}
								{@const isBlockCollapsed = collapsedBlock[block.blockId] ?? (block.funds.length === 0)}

								<!-- ── Level 2: Block / Region ── -->
								<div
									class="transition-all duration-150 overflow-hidden mx-1 my-0.5 rounded-[12px]
										{state === 'accept'
											? 'bg-[#11ec79]/[0.04] border-[1.5px] border-dashed border-[#11ec79]/40'
											: state === 'reject'
												? 'bg-[#fc1a1a]/[0.04] border-[1.5px] border-dashed border-[#fc1a1a]/40'
												: 'bg-white/[0.025] border border-transparent'}"
									role="region"
									aria-label="{block.displayLabel} allocation block"
									ondragover={handleDragOver}
									ondragenter={(e) => handleDragEnter(e, block.blockId)}
									ondragleave={(e) => handleDragLeave(e, block.blockId)}
									ondrop={(e) => handleDrop(e, block.blockId)}
								>
									<!-- Block header — distinct weight/color from Level 1 -->
									<button
										type="button"
										class="flex items-center w-full text-left justify-between px-3 py-2 cursor-pointer transition-colors {isBlockCollapsed ? '' : 'bg-[#141519]/40'}"
										onclick={(e) => toggleBlock(block.blockId, e)}
									>
										<div class="flex items-center gap-2 relative">
											<ChevronRight
												class="h-3.5 w-3.5 text-[#85a0bd]/50 transition-transform duration-200 shrink-0
													{isBlockCollapsed ? '' : 'rotate-90'}"
											/>
											<span class="text-[12px] font-medium text-[#a8b8cc] tracking-[0.01em]">{block.displayLabel}</span>
										</div>
										<div class="flex items-center gap-3 pr-2">
											<span class="text-[10px] text-[#85a0bd]/50 tabular-nums">{block.funds.length}</span>
											{#if block.funds.length > 0}
												<span class="text-[12px] font-bold text-white tabular-nums">{formatPercent(block.weight)}</span>
											{/if}
										</div>
									</button>

									<!-- ── Level 3: Fund cards ── -->
									{#if !isBlockCollapsed}
										<div class="flex flex-col bg-[#141519]/20" style="border-top: 1px solid rgba(64,66,73,0.3)">
											{#each block.funds as fund, i (fund.instrument_id)}
												{@const uniFund = workspace.universe.find(u => u.instrument_id === fund.instrument_id)}
												<div
													class="grid grid-cols-[16px_1fr_40px_minmax(110px,1.2fr)_65px_65px_60px_24px] gap-1 items-center px-3 py-1.5 transition-colors duration-100 group hover:bg-white/[0.03]"
													style={i < block.funds.length - 1 ? "border-bottom: 1px solid rgba(64, 66, 73, 0.15);" : ""}
												>
													<!-- Grip -->
													<div class="text-[#85a0bd]/20 shrink-0 cursor-grab active:cursor-grabbing">
														<GripVertical class="h-3 w-3" />
													</div>
													
													<div class="flex flex-col min-w-0">
														<div class="flex items-center gap-1 min-w-0">
															<span class="text-[11px] font-semibold text-white truncate">{fund.fund_name}</span>
														</div>
														{#if uniFund?.ticker}
															<span class="text-[9px] text-[#85a0bd]/60 tabular-nums">{uniFund.ticker}</span>
														{/if}
													</div>

													<!-- Score -->
													<span class="text-[10px] font-semibold text-[#cbccd1] tabular-nums text-right">
														{fund.score ?? uniFund?.manager_score ?? "—"}
													</span>

													<!-- Block Name -->
													<span class="text-[10px] text-[#85a0bd] truncate" title={block.displayLabel}>
														{block.displayLabel}
													</span>

													<!-- Class -->
													<span class="text-[9px] text-[#85a0bd]/70 truncate" title={formatAssetClass(uniFund?.asset_class ?? null)}>
														{formatAssetClass(uniFund?.asset_class ?? null)}
													</span>

													<!-- Geo -->
													<span class="text-[9px] text-[#85a0bd]/70 truncate" title={formatGeo(uniFund?.geography ?? null)}>
														{formatGeo(uniFund?.geography ?? null)}
													</span>

													<!-- Weight -->
													<span class="text-[12px] font-bold text-[#11ec79] tabular-nums text-right">
														{formatPercent(fund.weight)}
													</span>

													<!-- FactSheet -->
													<button
														type="button"
														class="flex items-center justify-center w-5 h-5 rounded text-[#85a0bd]/20 hover:text-[#0177fb] hover:bg-[#0177fb]/10 transition-colors opacity-0 group-hover:opacity-100"
														onclick={(e) => openFactSheet(fund.instrument_id, e)}
														title="Open Fact Sheet"
													>
														<ExternalLink class="h-2.5 w-2.5" />
													</button>
												</div>
											{/each}

											<!-- Persistent Drop Zone Inside Expanded Block -->
											<div class="flex items-center justify-center gap-2 min-h-[44px] px-4 py-1.5 bg-white/[0.008] border-t border-dashed border-[#404249]/30">
												<Plus class="h-3 w-3 text-[#85a0bd]/20" />
												<span class="text-[11px] text-[#85a0bd]/25 italic">Drag and drop additional assets</span>
											</div>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>

		<!-- Total strip -->
		{#if workspace.funds.length > 0}
			<div class="flex items-center justify-between px-4 py-3 bg-white/[0.03] rounded-[12px] shrink-0">
				<span class="text-[13px] font-semibold text-[#85a0bd]">{workspace.funds.length} funds total</span>
				<span class="text-[15px] font-bold text-white tabular-nums">
					{formatPercent(workspace.funds.reduce((s: number, f: { weight: number }) => s + f.weight, 0))}
				</span>
			</div>
		{/if}
	</div>
{/if}

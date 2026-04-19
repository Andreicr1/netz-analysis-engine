<!--
  BuilderTable — Continuous hierarchical tree table mirroring UniverseTable.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md
  User directive (2026-04-08 visual validation): the Builder column must be
  "um espelho estrutural" of the Universe column — one single continuous
  table with no isolating card backgrounds, matching the 3-level tree
  shape (Group → Block → Fund), same fonts, same borders, same cell
  padding, same indentation, same hover pattern.

  Structure (same tbody-per-group pattern as UniverseTable):

    <table>
      <thead>  Fund | Score | Weight | Actions
      <tbody>  (group 1)
        <tr>   Level 1 — Asset Class Group header row (colspan=5)
        <tr>   Level 2 — Block / Region header row (colspan=5, drop target)
        <tr>   Level 3 — Fund row (draggable OUT, drop target column)
        ... more L2+L3 pairs
      <tbody>  (group 2)
      ...

  Differences from UniverseTable:

    - Only 4 data columns (Fund / Score / Weight / Remove button) instead
      of 12. Same styling vocabulary, fewer cells.
    - Level 2 (Block) rows are ALSO drop targets for Universe → Builder
      adds. The whole row catches dragover/drop events and calls
      `workspace.addFundToBlock(fund, blockId)`.
    - Level 3 (Fund) rows are draggable OUT back to the Universe column
      for removal (same payload markers as PortfolioOverview used).
    - Group L1 rows show total weight on the right edge; Block L2 rows
      show block weight on the right edge.

  This replaces the legacy PortfolioOverview.svelte inside BuilderColumn.
  PortfolioOverview is kept at its path as dead code for reference until
  Phase D deletion after full visual validation.
-->
<script lang="ts">
	import GripVertical from "lucide-svelte/icons/grip-vertical";
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import X from "lucide-svelte/icons/x";
	import Plus from "lucide-svelte/icons/plus";
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { BLOCK_GROUPS, blockDisplay, groupDisplay } from "$wealth/constants/blocks";
	import { workspace, type UniverseFund } from "$wealth/state/portfolio-workspace.svelte";

	// ── Build 3-level tree (ported from PortfolioOverview) ────────

	const GROUP_ORDER = ["CASH & EQUIVALENTS", "EQUITIES", "FIXED INCOME", "ALTERNATIVES"];

	interface TreeFund {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		score: number | null;
		weight: number;
	}

	interface TreeBlock {
		blockId: string;
		displayLabel: string;
		funds: TreeFund[];
		weight: number;
	}

	interface TreeGroup {
		name: string;
		displayName: string;
		blocks: TreeBlock[];
		totalWeight: number;
		fundCount: number;
	}

	// Active blocks = blocks that have at least one fund in the Builder
	// OR at least one fund in the Universe (so empty blocks with
	// Universe candidates still show up as drop targets when the PM
	// wants to add a new block). Unused blocks stay hidden — no card
	// clutter.
	const activeBlockIds = $derived.by<Set<string>>(() => {
		const blocks = new Set<string>();
		for (const f of workspace.funds) blocks.add(f.block_id);
		return blocks;
	});

	const tree = $derived.by<TreeGroup[]>(() => {
		const groupMap = new Map<string, TreeGroup>();

		for (const [groupName, blockIds] of Object.entries(BLOCK_GROUPS)) {
			const blocks: TreeBlock[] = [];
			for (const blockId of blockIds) {
				if (!activeBlockIds.has(blockId)) continue;
				const rawFunds = (workspace.fundsByBlock[blockId] ?? []) as TreeFund[];
				const weight = rawFunds.reduce((s, f) => s + (f.weight ?? 0), 0);
				blocks.push({
					blockId,
					displayLabel: blockDisplay(blockId),
					funds: rawFunds,
					weight,
				});
			}
			if (blocks.length === 0) continue;

			groupMap.set(groupName, {
				name: groupName,
				displayName: groupDisplay(groupName),
				blocks,
				totalWeight: blocks.reduce((s, b) => s + b.weight, 0),
				fundCount: blocks.reduce((s, b) => s + b.funds.length, 0),
			});
		}

		// Catch unmapped blocks (OTHER group)
		const mappedBlockIds = new Set(Object.values(BLOCK_GROUPS).flat());
		const unmapped: TreeBlock[] = [];
		for (const blockId of activeBlockIds) {
			if (mappedBlockIds.has(blockId)) continue;
			const rawFunds = (workspace.fundsByBlock[blockId] ?? []) as TreeFund[];
			unmapped.push({
				blockId,
				displayLabel: blockDisplay(blockId),
				funds: rawFunds,
				weight: rawFunds.reduce((s, f) => s + (f.weight ?? 0), 0),
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

		// Deterministic ordering: Cash first, then declared order, then rest.
		const result: TreeGroup[] = [];
		for (const key of GROUP_ORDER) {
			const g = groupMap.get(key);
			if (g) {
				result.push(g);
				groupMap.delete(key);
			}
		}
		for (const g of groupMap.values()) result.push(g);
		return result;
	});

	// ── Collapse state per group and per block (in-memory only) ────

	let collapsedGroup = $state<Record<string, boolean>>({});
	let collapsedBlock = $state<Record<string, boolean>>({});

	function toggleGroup(name: string) {
		collapsedGroup[name] = !collapsedGroup[name];
	}

	function toggleBlock(blockId: string, e: Event) {
		e.stopPropagation();
		collapsedBlock[blockId] = !collapsedBlock[blockId];
	}

	// ── Drop target (Universe → Builder) per block ────────────────

	let dropState = $state<Record<string, "idle" | "accept" | "reject">>({});

	function getDragFund(e: DragEvent): UniverseFund | null {
		const instrumentId = e.dataTransfer?.getData("text/plain");
		if (!instrumentId) return null;
		return workspace.universe.find((f) => f.instrument_id === instrumentId) ?? null;
	}

	function isRemoveIntent(e: DragEvent): boolean {
		// A drag from a Builder row back to the Universe column carries
		// this intent marker; if we ever see it on a Builder block, we
		// ignore the drop (it was meant for the Universe column, not here).
		return e.dataTransfer?.types.includes("application/x-netz-allocated") ?? false;
	}

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
	}

	function handleDragEnter(e: DragEvent, blockId: string) {
		if (isRemoveIntent(e)) return;
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
		if (isRemoveIntent(e)) return;
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
			collapsedBlock[blockId] = false;
		}
	}

	// ── Drag source (Builder → Universe) for removal ────────────

	function handleRowDragStart(e: DragEvent, instrumentId: string) {
		if (!e.dataTransfer) return;
		e.dataTransfer.effectAllowed = "move";
		e.dataTransfer.setData("text/plain", instrumentId);
		e.dataTransfer.setData("application/x-netz-allocated", "1");
	}

	function handleRemove(instrumentId: string, e: Event) {
		e.stopPropagation();
		workspace.removeFund(instrumentId);
	}

	// ── Formatters ─────────────────────────────────────────────

	function formatScore(value: number | null | undefined): string {
		if (value == null || value === 0) return "—";
		return formatNumber(value, 0);
	}

	function formatWeight(value: number): string {
		return formatPercent(value, 2);
	}

	function tickerOf(instrumentId: string): string | null {
		return workspace.universe.find((u) => u.instrument_id === instrumentId)?.ticker ?? null;
	}
</script>

<!-- Same scroll/container pattern as UniverseTable.
     thead ALWAYS visible — the PM must see the matrix skeleton even
     when the portfolio has zero funds (Phase 11 mandate). -->
<div class="bt-wrap">
	<table class="bt-table" aria-label="Portfolio allocation — 3-level tree">
		<thead>
			<tr>
				<th scope="col" class="bt-th-grip" aria-label="Drag handle"></th>
				<th scope="col" class="bt-th-fund">Fund</th>
				<th scope="col" class="bt-th-num">Score</th>
				<th scope="col" class="bt-th-num">Weight</th>
				<th scope="col" class="bt-th-action" aria-label="Remove"></th>
			</tr>
		</thead>

		{#if tree.length === 0}
			<!-- Empty dropzone — inside tbody so the thead skeleton
			     stays visible. Invites DnD from the Universe table. -->
			<tbody>
				<tr>
					<td colspan="5" class="bt-dropzone">
						<div class="bt-dropzone-inner">
							<Plus size={24} />
							<p class="bt-dropzone-text">
								Drag funds from the Approved Universe to start building this portfolio.
							</p>
						</div>
					</td>
				</tr>
			</tbody>
		{:else}
			{#each tree as group (group.name)}
				{@const isGroupCollapsed = collapsedGroup[group.name] ?? false}

				<tbody class="bt-group">
					<!-- ── Level 1: Asset Class Group ── -->
					<tr class="bt-group-header">
						<td colspan="5">
							<button
								type="button"
								class="bt-group-toggle"
								onclick={() => toggleGroup(group.name)}
								aria-expanded={!isGroupCollapsed}
							>
								<ChevronRight
									class="bt-group-chevron {isGroupCollapsed ? '' : 'bt-group-chevron--open'}"
									size={16}
								/>
								<span class="bt-group-name">{group.displayName}</span>
								<span class="bt-group-count">{group.fundCount}</span>
								<span class="bt-group-weight">
									{group.totalWeight > 0 ? formatWeight(group.totalWeight) : ""}
								</span>
							</button>
						</td>
					</tr>

					{#if !isGroupCollapsed}
						{#each group.blocks as block (block.blockId)}
							{@const isBlockCollapsed = collapsedBlock[block.blockId] ?? false}
							{@const state = dropState[block.blockId] ?? "idle"}

							<!-- ── Level 2: Block / Region (drop target) ── -->
							<tr
								class="bt-block-header"
								class:bt-block-header--accept={state === "accept"}
								class:bt-block-header--reject={state === "reject"}
								ondragover={handleDragOver}
								ondragenter={(e) => handleDragEnter(e, block.blockId)}
								ondragleave={(e) => handleDragLeave(e, block.blockId)}
								ondrop={(e) => handleDrop(e, block.blockId)}
							>
								<td colspan="5">
									<button
										type="button"
										class="bt-block-toggle"
										onclick={(e) => toggleBlock(block.blockId, e)}
										aria-expanded={!isBlockCollapsed}
									>
										<ChevronRight
											class="bt-block-chevron {isBlockCollapsed ? '' : 'bt-block-chevron--open'}"
											size={14}
										/>
										<span class="bt-block-name">{block.displayLabel}</span>
										<span class="bt-block-count">{block.funds.length}</span>
										<span class="bt-block-weight">
											{block.funds.length > 0 ? formatWeight(block.weight) : ""}
										</span>
									</button>
								</td>
							</tr>

							{#if !isBlockCollapsed}
								{#each block.funds as fund (fund.instrument_id)}
									{@const ticker = tickerOf(fund.instrument_id)}
									<!-- ── Level 3: Fund row (draggable OUT for removal) ── -->
									<tr
										class="bt-row"
										draggable="true"
										ondragstart={(e) => handleRowDragStart(e, fund.instrument_id)}
										title="Drag back to the Approved Universe to remove"
									>
										<td class="bt-td-grip">
											<GripVertical size={14} />
										</td>
										<td class="bt-td-fund">
											<div class="bt-fund-name">{fund.fund_name}</div>
											{#if ticker}
												<div class="bt-fund-ticker">{ticker}</div>
											{/if}
										</td>
										<td class="bt-td-num">{formatScore(fund.score)}</td>
										<td class="bt-td-num bt-td-weight">{formatWeight(fund.weight)}</td>
										<td class="bt-td-action">
											<button
												type="button"
												class="bt-remove"
												onclick={(e) => handleRemove(fund.instrument_id, e)}
												aria-label="Remove fund from portfolio"
												title="Remove from portfolio"
											>
												<X size={14} />
											</button>
										</td>
									</tr>
								{/each}
							{/if}
						{/each}
					{/if}
				</tbody>
			{/each}
		{/if}
	</table>
</div>

<style>
	/* ── Hardcoded dark palette — identical to UniverseTable ──────
	 *   #141519  — column surface
	 *   #85a0bd  — muted text
	 *   #a8b8cc  — block label text (L2)
	 *   #cbccd1  — secondary text (L1)
	 *   #ffffff  — primary text (L3)
	 *   #404249  — border subtle
	 *   #0177fb  — brand primary
	 *   #11ec79  — weight highlight (Builder accent)
	 */

	.bt-wrap {
		height: 100%;
		overflow-y: auto;
		overflow-x: auto;
		background: #141519;
	}

	.bt-table {
		width: 100%;
		border-collapse: collapse;
		font-family: "Urbanist", sans-serif;
		font-size: 0.75rem;
		color: #ffffff;
		background: #141519;
	}

	/* ── Header (sticky) — mirrors UniverseTable ────────────── */

	.bt-table thead th {
		position: sticky;
		top: 0;
		background: #141519;
		color: #85a0bd;
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 10px 8px;
		text-align: left;
		border-bottom: 1px solid rgba(64, 66, 73, 0.6);
		white-space: nowrap;
		z-index: 2;
	}

	.bt-th-grip { width: 68px; padding-left: 16px; padding-right: 0; }
	.bt-th-fund { min-width: 220px; }
	.bt-th-num { text-align: right; font-variant-numeric: tabular-nums; min-width: 70px; }
	.bt-th-action { width: 40px; padding-right: 16px; }

	/* ── Level 1: Asset Class Group header ─────────────────── */

	.bt-group-header td {
		padding: 0;
		background: #141519;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
	}

	.bt-group-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 16px;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
	}

	.bt-group-toggle:hover {
		background: rgba(255, 255, 255, 0.03);
	}

	.bt-group-toggle :global(.bt-group-chevron) {
		color: #85a0bd;
		transition: transform 160ms ease;
		flex-shrink: 0;
	}

	.bt-group-toggle :global(.bt-group-chevron--open) {
		transform: rotate(90deg);
	}

	.bt-group-name {
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #cbccd1;
	}

	.bt-group-count {
		font-size: 0.625rem;
		color: #85a0bd;
		background: rgba(255, 255, 255, 0.05);
		padding: 1px 8px;
		border-radius: 999px;
		font-variant-numeric: tabular-nums;
	}

	.bt-group-weight {
		margin-left: auto;
		font-size: 0.8125rem;
		font-weight: 700;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
		padding-right: 16px;
	}

	/* ── Level 2: Block / Region header (+ drop target) ───── */

	.bt-block-header td {
		padding: 0;
		background: rgba(20, 21, 25, 0.6);
		border-bottom: 1px solid rgba(64, 66, 73, 0.2);
		transition: background-color 140ms ease, box-shadow 140ms ease;
	}

	.bt-block-header--accept td {
		background: rgba(17, 236, 121, 0.07);
		box-shadow: inset 0 0 0 1px rgba(17, 236, 121, 0.55);
	}

	.bt-block-header--reject td {
		background: rgba(252, 26, 26, 0.07);
		box-shadow: inset 0 0 0 1px rgba(252, 26, 26, 0.55);
	}

	.bt-block-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 6px 16px 6px 36px;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		color: #a8b8cc;
		font-family: "Urbanist", sans-serif;
	}

	.bt-block-toggle:hover {
		background: rgba(255, 255, 255, 0.02);
	}

	.bt-block-toggle :global(.bt-block-chevron) {
		color: rgba(133, 160, 189, 0.5);
		transition: transform 160ms ease;
		flex-shrink: 0;
	}

	.bt-block-toggle :global(.bt-block-chevron--open) {
		transform: rotate(90deg);
	}

	.bt-block-name {
		font-size: 0.75rem;
		font-weight: 500;
		color: #a8b8cc;
		letter-spacing: 0.01em;
	}

	.bt-block-count {
		font-size: 0.625rem;
		color: rgba(133, 160, 189, 0.6);
		font-variant-numeric: tabular-nums;
	}

	.bt-block-weight {
		margin-left: auto;
		font-size: 0.75rem;
		font-weight: 700;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
	}

	/* ── Level 3: Fund rows (drag source for removal) ─────── */

	.bt-row {
		border-bottom: 1px solid rgba(64, 66, 73, 0.25);
		cursor: grab;
		transition: background-color 120ms ease;
		background: #141519;
	}

	.bt-row:hover {
		background: rgba(255, 255, 255, 0.035);
	}

	.bt-row:active {
		cursor: grabbing;
	}

	.bt-row td {
		padding: 8px;
		vertical-align: middle;
	}

	.bt-td-grip {
		color: #85a0bd;
		opacity: 0.4;
		padding-left: 48px !important;
		padding-right: 0 !important;
		width: 68px;
	}

	.bt-td-fund {
		min-width: 220px;
	}

	.bt-fund-name {
		font-size: 0.8125rem;
		font-weight: 600;
		color: #ffffff;
		line-height: 1.2;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 260px;
	}

	.bt-fund-ticker {
		font-size: 0.6875rem;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
		margin-top: 2px;
	}

	.bt-td-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: #ffffff;
		font-size: 0.75rem;
		white-space: nowrap;
	}

	.bt-td-weight {
		font-weight: 700;
		color: #11ec79;
	}

	.bt-td-action {
		text-align: center;
		padding-right: 16px !important;
		width: 40px;
	}

	.bt-remove {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: none;
		background: transparent;
		color: rgba(133, 160, 189, 0.3);
		border-radius: 4px;
		cursor: pointer;
		transition: color 120ms ease, background 120ms ease;
		opacity: 0;
	}

	.bt-row:hover .bt-remove {
		opacity: 1;
	}

	.bt-remove:hover {
		color: #dc2626;
		background: rgba(220, 38, 38, 0.1);
	}

	/* ── Empty dropzone (inside tbody, under visible thead) ── */

	.bt-dropzone {
		padding: 0;
		border-bottom: none;
	}
	.bt-dropzone-inner {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		min-height: 280px;
		margin: 12px 16px;
		padding: 32px 24px;
		border: 2px dashed rgba(64, 66, 73, 0.5);
		border-radius: 8px;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
		transition: border-color 140ms ease, background 140ms ease;
	}
	.bt-dropzone-inner:hover {
		border-color: rgba(1, 119, 251, 0.4);
		background: rgba(1, 119, 251, 0.03);
	}
	.bt-dropzone-text {
		margin: 0;
		font-size: 0.8125rem;
		text-align: center;
		max-width: 320px;
		line-height: 1.5;
	}
</style>

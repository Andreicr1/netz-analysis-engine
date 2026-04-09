<!--
  UniverseTable — 3-level tree, 4-column lean layout (Phase 11).

  Reduced from 12 to 4 columns for the Builder context where the
  Universe table shares screen space with the Builder table. Detail
  metrics (AUM, returns, risk, correlation, momentum, liquidity, score)
  are available via FundDetailsDrawer on row click.

  Structure (matches the Builder 3-level tree):
    Level 1: Asset Class Group  (e.g. EQUITIES)
      Level 2: Block / Region  (e.g. North America — Large Cap)
        Level 3: Fund row (4 columns: Grip, Fund+Ticker, Asset Class, Expense)

  Interaction:
    - Drag (dragstart) → prepares fund for drop into Builder (Col 3)
    - Click → opens FundDetailsDrawer via onSelectFund callback
    - Allocated funds are dimmed (opacity 0.4, not draggable)
-->
<script lang="ts">
	import GripVertical from "lucide-svelte/icons/grip-vertical";
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import { formatPercent } from "@investintell/ui";
	import { BLOCK_GROUPS, blockDisplay, groupDisplay } from "$lib/constants/blocks";
	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";

	interface Props {
		funds: UniverseFund[];
		onSelectFund: (fund: UniverseFund) => void;
	}

	let { funds, onSelectFund }: Props = $props();

	const GROUP_ORDER = ["CASH & EQUIVALENTS", "EQUITIES", "FIXED INCOME", "ALTERNATIVES"];

	interface BlockNode {
		blockId: string;
		displayLabel: string;
		funds: UniverseFund[];
	}

	interface GroupNode {
		name: string;
		displayName: string;
		blocks: BlockNode[];
		fundCount: number;
	}

	const universeTree = $derived.by<GroupNode[]>(() => {
		function getGroupName(blockId: string): string {
			for (const [groupName, blocks] of Object.entries(BLOCK_GROUPS)) {
				if (blocks.includes(blockId)) return groupName;
			}
			return "OTHER";
		}

		const groups = new Map<string, Map<string, UniverseFund[]>>();
		for (const fund of funds) {
			const groupName = getGroupName(fund.block_id);
			let blockMap = groups.get(groupName);
			if (!blockMap) {
				blockMap = new Map();
				groups.set(groupName, blockMap);
			}
			const existing = blockMap.get(fund.block_id);
			if (existing) {
				existing.push(fund);
			} else {
				blockMap.set(fund.block_id, [fund]);
			}
		}

		const tree: GroupNode[] = [];
		function pushGroup(name: string) {
			const blockMap = groups.get(name);
			if (!blockMap || blockMap.size === 0) return;
			const blocks: BlockNode[] = [];
			let fundCount = 0;
			const canonicalOrder = BLOCK_GROUPS[name] ?? Array.from(blockMap.keys());
			for (const blockId of canonicalOrder) {
				const blockFunds = blockMap.get(blockId);
				if (blockFunds && blockFunds.length > 0) {
					blocks.push({
						blockId,
						displayLabel: blockDisplay(blockId),
						funds: blockFunds,
					});
					fundCount += blockFunds.length;
					blockMap.delete(blockId);
				}
			}
			for (const [blockId, blockFunds] of blockMap.entries()) {
				blocks.push({
					blockId,
					displayLabel: blockDisplay(blockId),
					funds: blockFunds,
				});
				fundCount += blockFunds.length;
			}
			tree.push({ name, displayName: groupDisplay(name), blocks, fundCount });
			groups.delete(name);
		}

		for (const canonicalGroup of GROUP_ORDER) pushGroup(canonicalGroup);
		for (const remaining of groups.keys()) pushGroup(remaining);
		return tree;
	});

	let collapsedGroup = $state<Record<string, boolean>>({});
	let collapsedBlock = $state<Record<string, boolean>>({});

	function toggleGroup(name: string) {
		collapsedGroup[name] = !collapsedGroup[name];
	}

	function toggleBlock(blockId: string, e: Event) {
		e.stopPropagation();
		collapsedBlock[blockId] = !collapsedBlock[blockId];
	}

	function isAllocated(instrumentId: string): boolean {
		return workspace.funds.some((f) => f.instrument_id === instrumentId);
	}

	function handleDragStart(e: DragEvent, fund: UniverseFund) {
		if (!e.dataTransfer) return;
		e.dataTransfer.effectAllowed = "copy";
		e.dataTransfer.setData("text/plain", fund.instrument_id);
	}

	function handleRowClick(fund: UniverseFund) {
		onSelectFund(fund);
	}

	function handleRowKeydown(e: KeyboardEvent, fund: UniverseFund) {
		if (e.key === "Enter" || e.key === " ") {
			e.preventDefault();
			onSelectFund(fund);
		}
	}

	function formatExpense(value: number | null | undefined): string {
		if (value == null) return "—";
		return formatPercent(value, 2);
	}
</script>

<div class="ut-wrap">
	<table class="ut-table" aria-label="Approved universe — drag funds to the Builder">
		<thead>
			<tr>
				<th scope="col" class="ut-th-grip" aria-label="Drag handle"></th>
				<th scope="col" class="ut-th-fund">Fund</th>
				<th scope="col" class="ut-th-class">Asset Class</th>
				<th scope="col" class="ut-th-expense">Expense</th>
			</tr>
		</thead>

		{#each universeTree as group (group.name)}
			{@const isGroupCollapsed = collapsedGroup[group.name] ?? false}

			<tbody class="ut-group">
				<tr class="ut-group-header">
					<td colspan="4">
						<button
							type="button"
							class="ut-group-toggle"
							onclick={() => toggleGroup(group.name)}
							aria-expanded={!isGroupCollapsed}
						>
							<ChevronRight
								class="ut-group-chevron {isGroupCollapsed ? '' : 'ut-group-chevron--open'}"
								size={16}
							/>
							<span class="ut-group-name">{group.displayName}</span>
							<span class="ut-group-count">{group.fundCount}</span>
						</button>
					</td>
				</tr>

				{#if !isGroupCollapsed}
					{#each group.blocks as block (block.blockId)}
						{@const isBlockCollapsed = collapsedBlock[block.blockId] ?? false}

						<tr class="ut-block-header">
							<td colspan="4">
								<button
									type="button"
									class="ut-block-toggle"
									onclick={(e) => toggleBlock(block.blockId, e)}
									aria-expanded={!isBlockCollapsed}
								>
									<ChevronRight
										class="ut-block-chevron {isBlockCollapsed ? '' : 'ut-block-chevron--open'}"
										size={14}
									/>
									<span class="ut-block-name">{block.displayLabel}</span>
									<span class="ut-block-count">{block.funds.length}</span>
								</button>
							</td>
						</tr>

						{#if !isBlockCollapsed}
							{#each block.funds as fund (fund.instrument_id)}
								{@const allocated = isAllocated(fund.instrument_id)}
								<tr
									class="ut-row"
									class:ut-row--allocated={allocated}
									draggable={!allocated}
									ondragstart={(e) => handleDragStart(e, fund)}
									onclick={() => handleRowClick(fund)}
									onkeydown={(e) => handleRowKeydown(e, fund)}
									tabindex="0"
									role="button"
									aria-label="{fund.fund_name} — click for details, drag to add"
								>
									<td class="ut-td-grip">
										<GripVertical size={14} />
									</td>
									<td class="ut-td-fund">
										<div class="ut-fund-name">{fund.fund_name}</div>
										{#if fund.ticker}
											<div class="ut-fund-ticker">{fund.ticker}</div>
										{/if}
									</td>
									<td class="ut-td-class">
										<span class="ut-chip">{fund.asset_class ?? "—"}</span>
									</td>
									<td class="ut-td-expense">{formatExpense(fund.expense_ratio ?? null)}</td>
								</tr>
							{/each}
						{/if}
					{/each}
				{/if}
			</tbody>
		{/each}
	</table>

	{#if universeTree.length === 0}
		<div class="ut-empty">No funds match the current filters.</div>
	{/if}
</div>

<style>
	.ut-wrap {
		height: 100%;
		overflow-y: auto;
		overflow-x: hidden;
	}

	.ut-table {
		width: 100%;
		border-collapse: collapse;
		font-family: "Urbanist", sans-serif;
		font-size: 0.75rem;
		color: #ffffff;
		background: #141519;
	}

	/* ── Header ──────────────────────────────────────────────── */
	.ut-table thead th {
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

	.ut-th-grip { width: 24px; padding-left: 4px; padding-right: 0; }
	.ut-th-class { width: 120px; }
	.ut-th-expense { width: 80px; text-align: right; }

	/* ── Group rows (L1) ─────────────────────────────────────── */
	.ut-group-header td {
		padding: 0;
		background: #141519;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
	}

	.ut-group-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 12px;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
	}
	.ut-group-toggle:hover {
		background: rgba(255, 255, 255, 0.03);
	}

	.ut-group-toggle :global(.ut-group-chevron) {
		color: #85a0bd;
		transition: transform 160ms ease;
		flex-shrink: 0;
	}
	.ut-group-toggle :global(.ut-group-chevron--open) {
		transform: rotate(90deg);
	}

	.ut-group-name {
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #cbccd1;
	}

	.ut-group-count {
		font-size: 0.625rem;
		color: #85a0bd;
		background: rgba(255, 255, 255, 0.05);
		padding: 1px 8px;
		border-radius: 999px;
		font-variant-numeric: tabular-nums;
	}

	/* ── Block rows (L2) ─────────────────────────────────────── */
	.ut-block-header td {
		padding: 0;
		background: rgba(20, 21, 25, 0.6);
		border-bottom: 1px solid rgba(64, 66, 73, 0.2);
	}

	.ut-block-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 6px 12px 6px 36px;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		color: #a8b8cc;
		font-family: "Urbanist", sans-serif;
	}
	.ut-block-toggle:hover {
		background: rgba(255, 255, 255, 0.02);
	}

	.ut-block-toggle :global(.ut-block-chevron) {
		color: rgba(133, 160, 189, 0.5);
		transition: transform 160ms ease;
		flex-shrink: 0;
	}
	.ut-block-toggle :global(.ut-block-chevron--open) {
		transform: rotate(90deg);
	}

	.ut-block-name {
		font-size: 0.75rem;
		font-weight: 500;
		color: #a8b8cc;
		letter-spacing: 0.01em;
	}

	.ut-block-count {
		font-size: 0.625rem;
		color: rgba(133, 160, 189, 0.6);
		font-variant-numeric: tabular-nums;
		margin-left: auto;
		padding-right: 8px;
	}

	/* ── Fund rows (L3) ──────────────────────────────────────── */
	.ut-row {
		border-bottom: 1px solid rgba(64, 66, 73, 0.25);
		cursor: grab;
		transition: background-color 120ms ease;
		background: #141519;
	}
	.ut-row:hover {
		background: rgba(255, 255, 255, 0.035);
	}
	.ut-row:focus-visible {
		outline: 2px solid #0177fb;
		outline-offset: -2px;
	}
	.ut-row:active {
		cursor: grabbing;
	}

	.ut-row--allocated {
		opacity: 0.4;
		cursor: default;
	}
	.ut-row--allocated:active {
		cursor: default;
	}

	.ut-row td {
		padding: 8px 8px;
		vertical-align: middle;
	}

	.ut-td-grip {
		color: #85a0bd;
		opacity: 0.4;
		padding-left: 48px !important;
		padding-right: 0 !important;
		width: 68px;
	}

	.ut-td-fund {
		min-width: 180px;
	}
	.ut-fund-name {
		font-size: 0.8125rem;
		font-weight: 600;
		color: #ffffff;
		line-height: 1.2;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
	}
	.ut-fund-ticker {
		font-size: 0.6875rem;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
		margin-top: 2px;
	}

	.ut-td-class {
		width: 120px;
	}
	.ut-chip {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 0.6875rem;
		font-weight: 500;
		background: rgba(255, 255, 255, 0.05);
		color: #cbccd1;
		white-space: nowrap;
	}

	.ut-td-expense {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: #ffffff;
		font-size: 0.75rem;
		white-space: nowrap;
		width: 80px;
	}

	.ut-empty {
		padding: 48px 16px;
		text-align: center;
		color: #85a0bd;
		font-size: 0.8125rem;
		background: #141519;
	}
</style>

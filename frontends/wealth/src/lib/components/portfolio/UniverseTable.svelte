<!--
  UniverseTable — 3-level institutional density tree.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §3.1

  Structure (matches the PortfolioOverview 3-level tree exactly so a
  fund appears in the same block in both the Universe and the Builder):

    Level 1: Asset Class Group  (e.g. EQUITIES)
      └─ Level 2: Block / Region  (e.g. North America — Large Cap)
           ├─ Level 3: Fund row  (12 Tier 1 density columns)
           ├─ Level 3: Fund row
           └─ ...

  Tier 1 column set (spec §3.1):

    1. Grip       |  2. Fund+Ticker  |  3. Asset class chip
    4. AUM        |  5. Expense %    |  6. 3Y return
    7. Risk-adj   |  8. Worst loss   |  9. Correlation → portfolio
    10. Momentum  | 11. Liquidity    | 12. Netz Score

  Why the 3-level match with Builder matters
  -------------------------------------------
  The previous 2-level version (group → fund) rendered a different
  tree shape than the Builder (group → block → fund), so the same
  fund appeared in visually different positions between the two
  columns. Harmonising the shape means the PM can scan "North America
  — Large Cap" in the Universe and see the candidates, then look at
  the same North America — Large Cap block in the Builder and see
  what's already allocated. 1:1 spatial parity eliminates mental
  model drift.

  Allocated funds are dimmed (opacity 0.4) to show "already in the
  Builder" without hiding them — the PM can still see the full menu.
  The Portfolio Builder is a staging area; funds can be dragged back
  out from the Builder to the Universe drop target (see UniverseColumn)
  which calls `workspace.removeFund()` and re-enables the row here.

  Nota sobre densidade: 12 colunas × ~44px de altura por linha gera
  uma tabela que precisa de pelo menos ~700px de largura da coluna
  Universe para respirar. No Estado B (45% do workspace) isso cabe
  confortavelmente em viewports ≥ 1280px. Em Estado C (30%) as
  colunas 9-11 escondem progressivamente via CSS container query —
  mas 6, 7, 8 nunca escondem (não-negociáveis).

  Jargon discipline: todo label/header usa labels institucionais do
  Risk Methodology v3 (Conditional Tail Risk, Maximum Drawdown,
  Risk-Adjusted Return) — zero CVaR/Sharpe/GARCH exposto.

  Nota sobre virtual scroll: adiado. O universo institucional típico
  tem 40-200 fundos aprovados; `overflow-y: auto` nativo é suficiente
  até ~500 linhas. Quando um tenant ultrapassar, migrar para
  @tanstack/svelte-virtual (já instalado) com createVirtualizer.
  Documentado como débito na spec §6.4.
-->
<script lang="ts">
	import GripVertical from "lucide-svelte/icons/grip-vertical";
	import TrendingUp from "lucide-svelte/icons/trending-up";
	import TrendingDown from "lucide-svelte/icons/trending-down";
	import Minus from "lucide-svelte/icons/minus";
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import { formatNumber, formatPercent, formatAUM } from "@investintell/ui";
	import { BLOCK_GROUPS, blockDisplay, groupDisplay } from "$lib/constants/blocks";
	import { humanizeMetric } from "$lib/i18n/quant-labels";
	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";

	interface Props {
		/** Funds to render — already filtered by the UniverseColumn wrapper. */
		funds: UniverseFund[];
		/** Called when a row is clicked — opens Analytics column (Estado B → C). */
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

	// Build the 3-level tree: Asset Class Group → Block/Region → Fund.
	// Same shape as the Builder's PortfolioOverview tree — guarantees
	// 1:1 spatial parity between the two columns.
	const universeTree = $derived.by<GroupNode[]>(() => {
		function getGroupName(blockId: string): string {
			for (const [groupName, blocks] of Object.entries(BLOCK_GROUPS)) {
				if (blocks.includes(blockId)) return groupName;
			}
			return "OTHER";
		}

		// First pass: bucket funds by group → block.
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

		// Second pass: materialise ordered tree.
		const tree: GroupNode[] = [];
		function pushGroup(name: string) {
			const blockMap = groups.get(name);
			if (!blockMap || blockMap.size === 0) return;
			const blocks: BlockNode[] = [];
			let fundCount = 0;
			// Sort block IDs within a group by BLOCK_GROUPS declaration
			// order so the shape matches PortfolioOverview deterministically.
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
			// Any leftover blocks not in canonical order (defensive).
			for (const [blockId, blockFunds] of blockMap.entries()) {
				blocks.push({
					blockId,
					displayLabel: blockDisplay(blockId),
					funds: blockFunds,
				});
				fundCount += blockFunds.length;
			}
			tree.push({
				name,
				displayName: groupDisplay(name),
				blocks,
				fundCount,
			});
			groups.delete(name);
		}

		for (const canonicalGroup of GROUP_ORDER) pushGroup(canonicalGroup);
		for (const remaining of groups.keys()) pushGroup(remaining);
		return tree;
	});

	// Collapse state per group and per block — in-memory, not localStorage.
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

	// ── Formatters for the new Tier 1 columns ────────────────────
	// All go through @investintell/ui — zero .toFixed / .toLocaleString.
	// Unknown / missing data renders as em-dash "—", never blank.

	function formatAumCell(value: number | null | undefined): string {
		if (value == null) return "—";
		return formatAUM(value);
	}

	function formatPercentCell(value: number | null | undefined, signed = false): string {
		if (value == null) return "—";
		const pct = value * 100;
		if (signed && pct > 0) return `+${formatPercent(value, 1)}`;
		return formatPercent(value, 1);
	}

	function formatRatioCell(value: number | null | undefined): string {
		if (value == null) return "—";
		return formatNumber(value, 2);
	}

	function formatScoreCell(value: number | null | undefined): string {
		if (value == null) return "—";
		return formatNumber(value, 0);
	}

	/** Correlation color scale: -1 (diversifying, green) → 0 (neutral) → +1 (concentrating, red).
	 *  Hex literals — no var() fallbacks (ensures consistent rendering in any theme context). */
	function correlationColor(value: number | null | undefined): string {
		if (value == null) return "#85a0bd";
		if (value <= -0.3) return "#16a34a";
		if (value <= 0.3) return "#cbccd1";
		if (value <= 0.7) return "#f59e0b";
		return "#dc2626";
	}

	function momentumIcon(value: number | null | undefined) {
		if (value == null) return { icon: Minus, color: "#85a0bd" };
		if (value > 0.15) return { icon: TrendingUp, color: "#16a34a" };
		if (value < -0.15) return { icon: TrendingDown, color: "#dc2626" };
		return { icon: Minus, color: "#85a0bd" };
	}
</script>

<!-- Scrollable data region — parent owns its own overflow/scroll -->
<div class="ut-wrap">
	<table class="ut-table" aria-label="Approved universe with risk and correlation metrics">
		<thead>
			<tr>
				<th scope="col" class="ut-th-grip" aria-label="Drag handle"></th>
				<th scope="col" class="ut-th-fund">Fund</th>
				<th scope="col" class="ut-th-class">Asset Class</th>
				<th scope="col" class="ut-th-num">AUM</th>
				<th scope="col" class="ut-th-num">Expense</th>
				<th scope="col" class="ut-th-num">3Y Return</th>
				<th scope="col" class="ut-th-num" title={humanizeMetric("risk_adjusted_return")}>
					Risk-Adjusted
				</th>
				<th scope="col" class="ut-th-num" title={humanizeMetric("max_drawdown")}>
					{humanizeMetric("max_drawdown")}
				</th>
				<th scope="col" class="ut-th-num ut-th-corr-col" title="Correlation to current portfolio">
					Corr → Port.
				</th>
				<th scope="col" class="ut-th-momentum ut-th-momentum-col" aria-label="Momentum indicator">
					Mom.
				</th>
				<th scope="col" class="ut-th-liquidity ut-th-liquidity-col">Liquidity</th>
				<th scope="col" class="ut-th-num">Netz Score</th>
			</tr>
		</thead>

		{#each universeTree as group (group.name)}
			{@const isGroupCollapsed = collapsedGroup[group.name] ?? false}

			<!-- ══ Level 1: Asset Class Group ══ -->
			<tbody class="ut-group">
				<tr class="ut-group-header">
					<td colspan="12">
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

						<!-- ── Level 2: Block / Region ── -->
						<tr class="ut-block-header">
							<td colspan="12">
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
								{@const corr = fund.correlation_to_portfolio ?? null}
								{@const mom = momentumIcon(fund.blended_momentum_score ?? null)}
								{@const MomIcon = mom.icon}
								<!-- ── Level 3: Fund row ── -->
								<tr
									class="ut-row"
									class:ut-row--allocated={allocated}
									draggable={!allocated}
									ondragstart={(e) => handleDragStart(e, fund)}
									onclick={() => handleRowClick(fund)}
									onkeydown={(e) => handleRowKeydown(e, fund)}
									tabindex="0"
									role="button"
									aria-label={`${fund.fund_name} — open details`}
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
									<td class="ut-td-num">{formatAumCell(fund.aum_usd ?? null)}</td>
									<td class="ut-td-num">{formatPercentCell(fund.expense_ratio ?? null)}</td>
									<td class="ut-td-num">{formatPercentCell(fund.return_3y_ann ?? null, true)}</td>
									<td class="ut-td-num">{formatRatioCell(fund.sharpe_1y ?? null)}</td>
									<td class="ut-td-num ut-td-loss">{formatPercentCell(fund.max_drawdown_1y ?? null)}</td>
									<td class="ut-td-num ut-td-corr ut-td-corr-col" style:color={correlationColor(corr)}>
										{formatRatioCell(corr)}
									</td>
									<td class="ut-td-momentum ut-td-momentum-col" style:color={mom.color}>
										<MomIcon size={14} />
									</td>
									<td class="ut-td-liquidity ut-td-liquidity-col">
										<span class="ut-liquidity-pill">{fund.liquidity_tier ?? "—"}</span>
									</td>
									<td class="ut-td-num ut-td-score">{formatScoreCell(fund.manager_score ?? null)}</td>
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
		overflow-x: auto;
		container-type: inline-size;
		container-name: ut;
	}

	/* ── Hardcoded dark palette (matches Screener #000/#141519/#85a0bd) ──
	 * All var() fallbacks removed — components force-render dark in any
	 * theme context. Colour constants mirror the Screener page exactly:
	 *   #000     — pure black outer canvas
	 *   #141519  — column surface
	 *   #85a0bd  — muted text (institutional blue-grey)
	 *   #cbccd1  — secondary text
	 *   #ffffff  — primary text
	 *   #404249  — border subtle
	 *   #0177fb  — brand primary
	 */

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
	.ut-th-fund { min-width: 220px; }
	.ut-th-class { width: 110px; }
	.ut-th-num { text-align: right; font-variant-numeric: tabular-nums; min-width: 70px; }
	.ut-th-momentum { width: 50px; text-align: center; }
	.ut-th-liquidity { width: 90px; }

	/* ── Group rows ──────────────────────────────────────────── */

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

	/* ── Level 2: Block / Region header ──────────────────────────
	 * Visual hierarchy:
	 *   Group (L1) — uppercase, bold, #cbccd1
	 *   Block (L2) — title case, medium, #a8b8cc, indented 24px
	 *   Fund  (L3) — small, #fff, standard row
	 */
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

	/* ── Data rows ───────────────────────────────────────────── */

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
		/* Indent 48px from the left edge so funds nest visually
		 * under the Level 2 Block / Region header above them. */
		padding-left: 48px !important;
		padding-right: 0 !important;
		width: 68px;
	}

	.ut-td-fund {
		min-width: 220px;
	}

	.ut-fund-name {
		font-size: 0.8125rem;
		font-weight: 600;
		color: #ffffff;
		line-height: 1.2;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 260px;
	}

	.ut-fund-ticker {
		font-size: 0.6875rem;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
		margin-top: 2px;
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

	.ut-td-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: #ffffff;
		font-size: 0.75rem;
		white-space: nowrap;
	}

	.ut-td-loss {
		color: #dc2626;
	}

	.ut-td-corr {
		font-weight: 600;
	}

	.ut-td-momentum {
		text-align: center;
	}

	.ut-liquidity-pill {
		display: inline-flex;
		align-items: center;
		padding: 1px 7px;
		border-radius: 999px;
		font-size: 0.625rem;
		font-weight: 500;
		background: rgba(255, 255, 255, 0.04);
		color: #cbccd1;
	}

	.ut-td-score {
		font-weight: 700;
		color: #ffffff;
	}

	.ut-empty {
		padding: 48px 16px;
		text-align: center;
		color: #85a0bd;
		font-size: 0.8125rem;
		background: #141519;
	}

	/* ── Responsive column hiding (container queries) ────────────
	 * In Estado B (Universe 45% of workspace) all 12 columns fit.
	 * In Estado C (Universe 30%) the less-critical columns hide
	 * progressively: correlation → momentum → liquidity, in order.
	 * The non-negotiable Tier 1 columns (AUM, Expense, 3Y Return,
	 * Risk-Adjusted, Maximum Drawdown) NEVER hide — they are the
	 * minimum institutional defensible set per spec §3.1.
	 */

	@container ut (max-width: 820px) {
		.ut-th-liquidity-col,
		.ut-td-liquidity-col {
			display: none;
		}
	}

	@container ut (max-width: 720px) {
		.ut-th-momentum-col,
		.ut-td-momentum-col {
			display: none;
		}
	}

	@container ut (max-width: 640px) {
		.ut-th-corr-col,
		.ut-td-corr-col {
			display: none;
		}
	}
</style>

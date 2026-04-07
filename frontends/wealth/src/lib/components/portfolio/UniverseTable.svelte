<!--
  UniverseTable — 12-column institutional density table.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §3.1

  Replaces the 5-column UniversePanel.svelte (deprecated for deletion
  in Phase D after visual validation). Tier 1 columns always visible:

    1. Grip       |  2. Fund+Ticker  |  3. Asset class chip
    4. AUM        |  5. Expense %    |  6. 3Y return
    7. Risk-adj   |  8. Worst loss   |  9. Correlation → portfolio
    10. Momentum  | 11. Liquidity    | 12. Netz Score

  Contract with parent:
    - Receives `funds: UniverseFund[]` already filtered/sorted by the
      UniverseColumn wrapper.
    - Emits `onSelectFund(fund)` when a row is clicked — opens the
      Analytics 3rd column (Estado B → Estado C transition).
    - Emits `onDragStart(e, fund)` native HTML5 drag — same contract
      as the legacy UniversePanel so allocation blocks keep receiving
      drops without modification.

  Grouping: BLOCK_GROUPS (Cash, Equities, Fixed Income, Alternatives),
  collapsible headers, count per group. `_searchKey` filter already
  applied upstream — this table does NOT filter, it only renders.

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
	import { BLOCK_GROUPS, groupDisplay } from "$lib/constants/blocks";
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

	// Group funds by BLOCK_GROUPS. Pre-computed in $derived.by so every
	// group render is O(1) during virtualisation.
	const universeTree = $derived.by(() => {
		const groupMap = new Map<string, UniverseFund[]>();

		function getGroupName(blockId: string): string {
			for (const [groupName, blocks] of Object.entries(BLOCK_GROUPS)) {
				if (blocks.includes(blockId)) return groupName;
			}
			return "OTHER";
		}

		for (const fund of funds) {
			const groupName = getGroupName(fund.block_id);
			if (!groupMap.has(groupName)) groupMap.set(groupName, []);
			groupMap.get(groupName)!.push(fund);
		}

		const result: { name: string; displayName: string; funds: UniverseFund[] }[] = [];
		for (const key of GROUP_ORDER) {
			const groupFunds = groupMap.get(key);
			if (groupFunds && groupFunds.length > 0) {
				result.push({ name: key, displayName: groupDisplay(key), funds: groupFunds });
				groupMap.delete(key);
			}
		}
		for (const [key, groupFunds] of groupMap.entries()) {
			if (groupFunds.length > 0) {
				result.push({ name: key, displayName: groupDisplay(key), funds: groupFunds });
			}
		}
		return result;
	});

	// Per-group collapse state — in-memory, not localStorage (by rule).
	let collapsed = $state<Record<string, boolean>>({});

	function toggleGroup(group: string) {
		collapsed[group] = !collapsed[group];
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
			{@const isCollapsed = collapsed[group.name] ?? false}
			<tbody class="ut-group">
				<tr class="ut-group-header">
					<td colspan="12">
						<button
							type="button"
							class="ut-group-toggle"
							onclick={() => toggleGroup(group.name)}
							aria-expanded={!isCollapsed}
						>
							<ChevronRight
								class="ut-group-chevron {isCollapsed ? '' : 'ut-group-chevron--open'}"
								size={14}
							/>
							<span class="ut-group-name">{group.displayName}</span>
							<span class="ut-group-count">{group.funds.length}</span>
						</button>
					</td>
				</tr>

				{#if !isCollapsed}
					{#each group.funds as fund (fund.instrument_id)}
						{@const allocated = isAllocated(fund.instrument_id)}
						{@const corr = fund.correlation_to_portfolio ?? null}
						{@const mom = momentumIcon(fund.blended_momentum_score ?? null)}
						{@const MomIcon = mom.icon}
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
		padding-left: 4px !important;
		padding-right: 0 !important;
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

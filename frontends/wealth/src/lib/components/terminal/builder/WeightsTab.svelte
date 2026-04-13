<!--
  WeightsTab — WEIGHTS tab in the Builder results panel (right column).

  Read-only display of proposed weights grouped by asset class.
  Tree structure: Group -> Block -> Fund. No drag-drop.
  Data sourced from workspace.funds / workspace.fundsByBlock.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { BLOCK_GROUPS, blockDisplay, groupDisplay } from "$lib/constants/blocks";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	// ── Build 3-level tree (same logic as BuilderTable, DnD stripped) ──

	const GROUP_ORDER = ["CASH & EQUIVALENTS", "EQUITIES", "FIXED INCOME", "ALTERNATIVES"];

	interface TreeFund {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		score: number | null;
		weight: number;
		ticker?: string | null;
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

		// Catch unmapped blocks
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

	const hasRun = $derived(workspace.constructionRun !== null);

	// ── Run diff data for Previous column (Session 3) ──
	// Fetch diff when a construction run completes
	$effect(() => {
		const run = workspace.constructionRun;
		if (run?.run_id && !workspace.runDiff && !workspace.isLoadingDiff) {
			workspace.fetchRunDiff(run.run_id);
		}
	});

	const diffData = $derived(workspace.runDiff?.weight_delta ?? null);

	function previousWeight(instrumentId: string, currentWeight: number): string {
		if (!diffData) return "\u2014";
		const entry = diffData[instrumentId];
		if (!entry) return "\u2014";
		return formatWeight(entry.from);
	}

	// ── Collapse state ──
	let collapsedGroup = $state<Record<string, boolean>>({});

	function toggleGroup(name: string) {
		collapsedGroup[name] = !collapsedGroup[name];
	}

	// ── Delta formatting ──
	function deltaColor(weight: number): string {
		if (weight > 0.0001) return "var(--terminal-status-success)";
		if (weight < -0.0001) return "var(--terminal-status-error)";
		return "var(--terminal-fg-muted)";
	}

	function formatDelta(weight: number): string {
		if (Math.abs(weight) < 0.0001) return "\u2014";
		const sign = weight > 0 ? "+" : "";
		return sign + formatPercent(weight, 2);
	}

	function formatWeight(value: number): string {
		return formatPercent(value, 2);
	}

	function formatScore(value: number | null | undefined): string {
		if (value == null || value === 0) return "\u2014";
		return formatNumber(value, 0);
	}
</script>

<div class="wt-root">
	{#if tree.length === 0}
		<div class="wt-empty">
			{#if hasRun}
				No instruments in portfolio
			{:else}
				Run construction to see proposed weights
			{/if}
		</div>
	{:else}
		<table class="wt-table" aria-label="Proposed portfolio weights">
			<thead>
				<tr>
					<th class="wt-th wt-th-name">Fund</th>
					<th class="wt-th wt-th-num">Score</th>
					<th class="wt-th wt-th-num">Weight</th>
					<th class="wt-th wt-th-num">Previous</th>
					<th class="wt-th wt-th-num">Delta</th>
				</tr>
			</thead>

			{#each tree as group (group.name)}
				{@const isCollapsed = collapsedGroup[group.name] ?? false}
				<tbody>
					<tr
						class="wt-group-row"
						role="button"
						tabindex="0"
						onclick={() => toggleGroup(group.name)}
						onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleGroup(group.name); } }}
					>
						<td class="wt-group-name" colspan="3">
							<span class="wt-chevron" class:wt-chevron--open={!isCollapsed}>&rsaquo;</span>
							{group.displayName}
							<span class="wt-group-count">({group.fundCount})</span>
						</td>
						<td class="wt-group-weight" colspan="2">
							{formatWeight(group.totalWeight)}
						</td>
					</tr>

					{#if !isCollapsed}
						{#each group.blocks as block (block.blockId)}
							<tr class="wt-block-row">
								<td class="wt-block-name" colspan="3">
									{block.displayLabel}
								</td>
								<td class="wt-block-weight" colspan="2">
									{formatWeight(block.weight)}
								</td>
							</tr>

							{#each block.funds as fund (fund.instrument_id)}
								<tr class="wt-fund-row">
									<td class="wt-fund-name">
										<span class="wt-fund-label">{fund.fund_name}</span>
										{#if fund.ticker}
											<span class="wt-fund-ticker">{fund.ticker}</span>
										{/if}
									</td>
									<td class="wt-fund-num">{formatScore(fund.score)}</td>
									<td class="wt-fund-num">{formatWeight(fund.weight)}</td>
									<td class="wt-fund-num wt-fund-ghost">{previousWeight(fund.instrument_id, fund.weight)}</td>
									<td class="wt-fund-num">
										<span class="wt-delta" style="color: {deltaColor(fund.weight)}">
											{formatDelta(fund.weight)}
										</span>
										{#if Math.abs(fund.weight) > 0.0001}
											<div class="wt-delta-bar">
												<div
													class="wt-delta-fill"
													style="width: {Math.min(Math.abs(fund.weight) * 500, 100)}%; background: {deltaColor(fund.weight)};"
												></div>
											</div>
										{/if}
									</td>
								</tr>
							{/each}
						{/each}
					{/if}
				</tbody>
			{/each}

			<tfoot>
				<tr class="wt-total-row">
					<td class="wt-total-label" colspan="2">Total</td>
					<td class="wt-total-value">{formatWeight(workspace.totalWeight)}</td>
					<td class="wt-total-value wt-fund-ghost">&mdash;</td>
					<td class="wt-total-value"></td>
				</tr>
			</tfoot>
		</table>
	{/if}
</div>

<style>
	.wt-root {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
	}

	.wt-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-12);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.wt-table {
		width: 100%;
		border-collapse: collapse;
	}

	.wt-th {
		position: sticky;
		top: 0;
		background: var(--terminal-bg-panel);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		text-align: left;
		font-size: var(--terminal-text-10);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		border-bottom: var(--terminal-border-hairline);
		z-index: 1;
	}

	.wt-th-num {
		text-align: right;
		width: 80px;
	}

	.wt-th-name {
		width: auto;
	}

	/* Group row */
	.wt-group-row {
		cursor: pointer;
		border-bottom: var(--terminal-border-hairline);
	}

	.wt-group-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.wt-group-name {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-weight: 700;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.wt-chevron {
		display: inline-block;
		width: 12px;
		transition: transform var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.wt-chevron--open {
		transform: rotate(90deg);
	}

	.wt-group-count {
		color: var(--terminal-fg-tertiary);
		font-weight: 400;
		margin-left: var(--terminal-space-1);
	}

	.wt-group-weight {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		text-align: right;
		font-weight: 700;
		color: var(--terminal-fg-primary);
	}

	/* Block row */
	.wt-block-row {
		border-bottom: 1px solid var(--terminal-bg-panel-raised);
	}

	.wt-block-name {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		padding-left: var(--terminal-space-6);
		font-weight: 600;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.wt-block-weight {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		text-align: right;
		font-weight: 600;
		color: var(--terminal-fg-secondary);
	}

	/* Fund row */
	.wt-fund-row {
		border-bottom: 1px solid var(--terminal-bg-panel-raised);
	}

	.wt-fund-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.wt-fund-name {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		padding-left: var(--terminal-space-8);
	}

	.wt-fund-label {
		color: var(--terminal-fg-primary);
	}

	.wt-fund-ticker {
		margin-left: var(--terminal-space-1);
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}

	.wt-fund-num {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		text-align: right;
	}

	.wt-fund-ghost {
		color: var(--terminal-fg-muted);
	}

	.wt-delta {
		font-weight: 600;
	}

	.wt-delta-bar {
		margin-top: 2px;
		height: 2px;
		background: var(--terminal-fg-muted);
		width: 60px;
		margin-left: auto;
	}

	.wt-delta-fill {
		height: 100%;
		transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
	}

	/* Total row */
	.wt-total-row {
		border-top: var(--terminal-border-strong);
	}

	.wt-total-label {
		padding: var(--terminal-space-2);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
	}

	.wt-total-value {
		padding: var(--terminal-space-2);
		text-align: right;
		font-weight: 700;
		color: var(--terminal-fg-primary);
	}
</style>

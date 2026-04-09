<!--
  LiveAllocationsTable — Phase 8 Live Workbench holdings surface.

  Renders ``portfolio.fund_selection_schema.funds`` as a dense
  tabular view grouped by allocation block. Each block shows its
  total weight header row followed by the individual fund rows,
  sorted by weight DESC so the biggest positions always sit at
  the top of each block.

  Per the Phase 8 user mandate:
    - No ECharts. Pure HTML table.
    - Reuses formatPercent + formatNumber from @investintell/ui.
    - Extremely tight scope — no trading actions, no execution
      buttons, no edit affordances. Monitoring surface only.

  The table is keyboard-accessible and mousewheel-scrollable
  inside its own scroll container so it never pushes the KPI
  strip off the top of the workbench.
-->
<script lang="ts">
	import { EmptyState, formatPercent, formatNumber } from "@investintell/ui";
	import { blockLabel } from "$lib/constants/blocks";
	import type {
		ModelPortfolio,
		InstrumentWeight,
	} from "$lib/types/model-portfolio";

	interface Props {
		portfolio: ModelPortfolio;
	}

	let { portfolio }: Props = $props();

	interface BlockGroup {
		blockId: string;
		blockName: string;
		totalWeight: number;
		funds: InstrumentWeight[];
	}

	const grouped = $derived.by<BlockGroup[]>(() => {
		const funds = portfolio.fund_selection_schema?.funds ?? [];
		if (funds.length === 0) return [];

		const map = new Map<string, BlockGroup>();
		for (const f of funds) {
			const key = f.block_id || "unallocated";
			if (!map.has(key)) {
				map.set(key, {
					blockId: key,
					blockName: blockLabel(key) || key,
					totalWeight: 0,
					funds: [],
				});
			}
			const group = map.get(key)!;
			group.totalWeight += f.weight ?? 0;
			group.funds.push(f);
		}
		// Sort blocks by total weight DESC, funds within each block
		// by weight DESC — biggest positions always on top.
		const list = Array.from(map.values());
		list.sort((a, b) => b.totalWeight - a.totalWeight);
		for (const g of list) {
			g.funds.sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
		}
		return list;
	});

	const isEmpty = $derived(grouped.length === 0);
</script>

<section class="lat-root" aria-label="Active allocations">
	<header class="lat-header">
		<span class="lat-kicker">Active allocations</span>
		<span class="lat-title">Approved weights by block</span>
	</header>

	{#if isEmpty}
		<div class="lat-empty">
			<EmptyState
				title="No holdings on this portfolio"
				message="The portfolio has no fund selection schema. Re-run construction from the Builder to populate allocations."
			/>
		</div>
	{:else}
		<div class="lat-scroll">
			<table class="lat-table">
				<thead>
					<tr>
						<th scope="col">Instrument</th>
						<th scope="col" class="lat-num">Weight</th>
						<th scope="col" class="lat-num">Score</th>
						<th scope="col">Type</th>
					</tr>
				</thead>
				<tbody>
					{#each grouped as group (group.blockId)}
						<!-- Block header row -->
						<tr class="lat-block-row">
							<th colspan="2" scope="rowgroup" class="lat-block-name">
								{group.blockName}
							</th>
							<td class="lat-num lat-block-weight">
								{formatPercent(group.totalWeight, 2)}
							</td>
							<td></td>
						</tr>
						<!-- Fund rows inside the block -->
						{#each group.funds as fund (fund.instrument_id)}
							<tr class="lat-fund-row">
								<td class="lat-fund-name">
									<span class="lat-fund-label">{fund.fund_name}</span>
								</td>
								<td class="lat-num">
									{formatPercent(fund.weight ?? 0, 2)}
								</td>
								<td class="lat-num lat-muted">
									{fund.score !== null && fund.score !== undefined
										? formatNumber(fund.score, 2)
										: "—"}
								</td>
								<td class="lat-muted">
									{fund.instrument_type ?? "—"}
								</td>
							</tr>
						{/each}
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</section>

<style>
	.lat-root {
		display: flex;
		flex-direction: column;
		min-height: 0;
		flex: 1;
		background: #141519;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		font-family: "Urbanist", system-ui, sans-serif;
		overflow: hidden;
	}

	.lat-header {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 16px 20px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		flex-shrink: 0;
	}
	.lat-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.lat-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}

	.lat-empty {
		padding: 32px 24px;
	}

	.lat-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.lat-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.lat-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
		background: #141519;
	}
	.lat-table thead th {
		padding: 10px 16px;
		text-align: left;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.lat-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.lat-muted {
		color: var(--ii-text-muted, #85a0bd);
	}

	.lat-block-row {
		background: rgba(255, 255, 255, 0.02);
	}
	.lat-block-row th,
	.lat-block-row td {
		padding: 10px 16px;
		border-top: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.lat-block-name {
		font-size: 11px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		text-align: left;
	}
	.lat-block-weight {
		font-size: 12px;
		font-weight: 700;
		color: var(--ii-primary, #4ca0ff);
	}

	.lat-fund-row td {
		padding: 10px 16px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.2);
	}
	.lat-fund-name {
		max-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lat-fund-label {
		display: inline-block;
		padding-left: 12px;
		color: var(--ii-text-secondary, #cbccd1);
	}
</style>

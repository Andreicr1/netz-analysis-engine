<!--
  OverlapScannerPanel — Detects hidden concentration risk: equity overlaps + cross-fund holdings (ETF/fund-of-fund).
  Mock deterministic data derived from workspace.funds for reactivity.
-->
<script lang="ts">
	import { AlertBanner, EmptyState, formatPercent } from "@investintell/ui";
	import { Badge } from "@investintell/ui/components/ui/badge";
	import Scan from "lucide-svelte/icons/scan";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	interface OverlapSource {
		fund: string;
		weight: number;
	}

	interface OverlapEntry {
		asset: string;
		ticker: string;
		type: "Equity" | "Registered Fund" | "ETF" | "Corporate Bond";
		totalWeight: number;
		sources: OverlapSource[];
	}

	let fundCount = $derived(workspace.funds.length);

	let overlaps = $derived.by<OverlapEntry[]>(() => {
		if (fundCount < 2) return [];

		// Deterministic mock — shifts slightly with fund count for reactivity
		const shift = (fundCount % 4) * 0.002;

		return [
			{
				asset: "Microsoft Corp",
				ticker: "MSFT",
				type: "Equity",
				totalWeight: 0.045 + shift,
				sources: [
					{ fund: "Fund A", weight: 0.025 + shift },
					{ fund: "Fund B", weight: 0.02 },
				],
			},
			{
				asset: "SPDR S&P 500 ETF",
				ticker: "SPY",
				type: "Registered Fund",
				totalWeight: 0.032 + shift * 0.5,
				sources: [
					{ fund: "Fund A", weight: 0.012 },
					{ fund: "Fund C", weight: 0.02 + shift * 0.5 },
				],
			},
			{
				asset: "Apple Inc",
				ticker: "AAPL",
				type: "Equity",
				totalWeight: 0.038 - shift * 0.3,
				sources: [
					{ fund: "Fund A", weight: 0.022 - shift * 0.3 },
					{ fund: "Fund B", weight: 0.016 },
				],
			},
			{
				asset: "iShares Core US Aggregate Bond",
				ticker: "AGG",
				type: "ETF",
				totalWeight: 0.028 + shift * 0.8,
				sources: [
					{ fund: "Fund B", weight: 0.015 + shift * 0.4 },
					{ fund: "Fund C", weight: 0.013 + shift * 0.4 },
				],
			},
			{
				asset: "NVIDIA Corp",
				ticker: "NVDA",
				type: "Equity",
				totalWeight: 0.034 + shift * 1.2,
				sources: [
					{ fund: "Fund A", weight: 0.019 + shift * 0.6 },
					{ fund: "Fund C", weight: 0.015 + shift * 0.6 },
				],
			},
		];
	});

	let totalConcentration = $derived(
		overlaps.reduce((sum, o) => sum + o.totalWeight, 0),
	);

	let crossHoldingCount = $derived(
		overlaps.filter((o) => o.type !== "Equity").length,
	);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to scan for overlapping holdings."
		/>
	</div>
{:else if fundCount < 2}
	<div class="p-6">
		<EmptyState
			title="Not enough funds to scan"
			message="Add at least two funds to the portfolio to detect overlapping holdings."
		/>
	</div>
{:else}
	<div class="overlap-panel">
		<div class="overlap-header">
			<Scan class="h-4 w-4" style="color: var(--ii-warning);" />
			<span class="overlap-title">Overlap Scanner</span>
			<span class="overlap-subtitle">
				{overlaps.length} overlaps &middot; {formatPercent(totalConcentration)} concentrated
			</span>
		</div>

		<AlertBanner variant="warning">
			<span class="alert-text">
				<strong>Concentration Alert:</strong> Detected {overlaps.length - crossHoldingCount} overlapping equities
				and {crossHoldingCount} cross-fund holdings. Watch out for potential double-fee exposure.
			</span>
		</AlertBanner>

		<div class="table-wrapper">
			<table class="overlap-table">
				<thead>
					<tr>
						<th class="th-asset">Underlying Asset</th>
						<th class="th-weight">Consolidated Weight</th>
						<th class="th-sources">Source Funds</th>
					</tr>
				</thead>
				<tbody>
					{#each overlaps as row (row.ticker)}
						<tr class="overlap-row">
							<td class="td-asset">
								<div class="asset-info">
									<span class="asset-name">{row.asset}</span>
									<span class="asset-ticker">{row.ticker}</span>
								</div>
								<Badge variant="secondary">{row.type}</Badge>
							</td>
							<td class="td-weight">
								<span class="weight-value">{formatPercent(row.totalWeight)}</span>
							</td>
							<td class="td-sources">
								<div class="source-badges">
									{#each row.sources as src}
										<Badge variant="outline">
											{src.fund}: {formatPercent(src.weight)}
										</Badge>
									{/each}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{/if}

<style>
	.overlap-panel {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 16px;
		height: 100%;
	}

	.overlap-header {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.overlap-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.overlap-subtitle {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		margin-left: auto;
	}

	.alert-text {
		font-size: var(--ii-text-small, 0.8125rem);
		line-height: 1.5;
	}

	.table-wrapper {
		flex: 1;
		overflow-y: auto;
		min-height: 0;
	}

	.overlap-table {
		width: 100%;
		border-collapse: collapse;
	}

	.overlap-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
		background: var(--ii-surface);
	}

	.overlap-table th {
		padding: 8px 12px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		text-align: left;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.th-weight {
		text-align: right;
		width: 160px;
	}

	.th-sources {
		width: 280px;
	}

	.overlap-row {
		border-bottom: 1px solid var(--ii-border-subtle);
		transition: background 120ms ease;
	}

	.overlap-row:hover {
		background: var(--ii-surface-alt);
	}

	.overlap-table td {
		padding: 10px 12px;
		vertical-align: middle;
	}

	.td-asset {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.asset-info {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}

	.asset-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.asset-ticker {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.td-weight {
		text-align: right;
	}

	.weight-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-warning);
	}

	.source-badges {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
</style>

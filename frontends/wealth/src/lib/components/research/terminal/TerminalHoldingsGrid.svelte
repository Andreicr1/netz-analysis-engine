<script lang="ts">
	import { formatNumber, formatPercent } from "@investintell/ui";

	interface Props {
		ticker: string;
	}

	let { ticker }: Props = $props();

	type Holding = {
		issuer_name: string;
		sector: string;
		weight: number;
		market_value: number;
	};

	type SectorInfo = {
		name: string;
		weight: number;
		holdings_count: number;
	};

	type HoldingsData = {
		top_holdings: Holding[];
		sector_breakdown: SectorInfo[];
	};

	let data = $state<HoldingsData | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		if (!ticker || ticker === "PORTFOLIO") {
			data = null;
			return;
		}

		let controller = new AbortController();

		async function fetchHoldings() {
			loading = true;
			error = null;
			try {
				const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
				const res = await fetch(`${API_BASE}/wealth/discovery/funds/${ticker}/analysis/holdings/top`, {
					signal: controller.signal,
				});
				if (!res.ok) {
					throw new Error(`Failed to fetch holdings: ${res.statusText}`);
				}
				data = await res.json();
			} catch (err: any) {
				if (err.name !== "AbortError") {
					error = err.message;
				}
			} finally {
				loading = false;
			}
		}

		fetchHoldings();

		return () => {
			controller.abort();
		};
	});
</script>

<div class="h-root">
	{#if loading}
		<div class="h-message">Loading holdings...</div>
	{:else if error}
		<div class="h-message h-error">{error}</div>
	{:else if !data}
		<div class="h-message">No holdings data available.</div>
	{:else}
		<div class="h-grid">
			<!-- Top Holdings Section -->
			<div class="h-section">
				<div class="h-section-header">TOP HOLDINGS</div>
				<div class="h-scroll-area">
					<table class="h-table">
						<thead>
							<tr>
								<th class="text-left">ISSUER</th>
								<th class="text-left">SECTOR</th>
								<th class="text-right">WEIGHT</th>
								<th class="text-right">MARKET VALUE</th>
							</tr>
						</thead>
						<tbody>
							{#each data.top_holdings as holding}
								<tr>
									<td class="text-left td-primary">{holding.issuer_name}</td>
									<td class="text-left td-secondary">{holding.sector}</td>
									<td class="text-right">{formatPercent(holding.weight * 100)}</td>
									<td class="text-right">${formatNumber(holding.market_value)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Sector Breakdown Section -->
			<div class="h-section">
				<div class="h-section-header">SECTOR BREAKDOWN</div>
				<div class="h-scroll-area">
					<table class="h-table">
						<thead>
							<tr>
								<th class="text-left">SECTOR</th>
								<th class="text-right">COUNT</th>
								<th class="text-right">WEIGHT</th>
							</tr>
						</thead>
						<tbody>
							{#each data.sector_breakdown as sector}
								<tr class="sector-row">
									<td class="text-left sector-cell">
										<div
											class="sector-bar"
											style="width: {sector.weight * 100}%;"
										></div>
										<span class="sector-name">{sector.name}</span>
									</td>
									<td class="text-right">{sector.holdings_count}</td>
									<td class="text-right">{formatPercent(sector.weight * 100)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.h-root {
		width: 100%;
		height: 100%;
		background: var(--terminal-bg-panel);
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		font-family: var(--terminal-font-mono);
	}

	.h-message {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
		font-variant-numeric: tabular-nums;
	}

	.h-error {
		color: var(--terminal-status-error);
	}

	.h-grid {
		display: grid;
		grid-template-rows: 1fr 1fr;
		gap: 2px;
		width: 100%;
		height: 100%;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	@media (min-width: 1024px) {
		.h-grid {
			grid-template-rows: 100%;
			grid-template-columns: 2fr 1fr;
		}
	}

	.h-section {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
	}

	.h-section-header {
		height: 24px;
		line-height: 24px;
		padding: 0 8px;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.05em;
		color: var(--terminal-fg-secondary);
		background: var(--terminal-bg-panel);
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.h-scroll-area {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow-y: auto;
	}

	.h-scroll-area::-webkit-scrollbar {
		width: 4px;
		height: 4px;
	}
	.h-scroll-area::-webkit-scrollbar-track {
		background: transparent;
	}
	.h-scroll-area::-webkit-scrollbar-thumb {
		background: var(--terminal-fg-disabled);
	}
	.h-scroll-area::-webkit-scrollbar-thumb:hover {
		background: var(--terminal-fg-muted);
	}

	.h-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--terminal-text-11);
		font-variant-numeric: tabular-nums;
		color: var(--terminal-fg-secondary);
	}

	.h-table th {
		position: sticky;
		top: 0;
		z-index: 20;
		background: var(--terminal-bg-panel);
		color: var(--terminal-fg-tertiary);
		font-weight: 600;
		padding: 4px 8px;
		border-bottom: var(--terminal-border-hairline);
		white-space: nowrap;
	}

	.h-table td {
		padding: 4px 8px;
		border-bottom: 1px solid var(--terminal-fg-disabled);
		white-space: nowrap;
	}

	.h-table tr:hover td {
		background: var(--terminal-bg-panel-raised);
	}

	.text-left { text-align: left; }
	.text-right { text-align: right; }

	.td-primary {
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}

	.td-secondary {
		color: var(--terminal-fg-tertiary);
	}

	.sector-row {
		position: relative;
	}

	.sector-cell {
		position: relative;
	}

	.sector-bar {
		position: absolute;
		left: 0;
		top: 0;
		height: 100%;
		background: var(--terminal-fg-disabled);
		z-index: 0;
	}

	.sector-name {
		position: relative;
		z-index: 1;
		padding-left: 4px;
		color: var(--terminal-fg-primary);
	}
</style>

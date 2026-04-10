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
				// We assume ticker acts as the external_id here
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
									<td class="text-left font-medium text-white">{holding.issuer_name}</td>
									<td class="text-left text-gray-400">{holding.sector}</td>
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
								<tr class="relative">
									<td class="text-left relative z-10">
										<div
											class="h-full absolute left-0 top-0 bg-[#1e293b] z-[-1]"
											style="width: {sector.weight * 100}%;"
										></div>
										<span class="pl-1 text-white">{sector.name}</span>
									</td>
									<td class="text-right z-10 relative">{sector.holdings_count}</td>
									<td class="text-right z-10 relative">{formatPercent(sector.weight * 100)}</td>
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
		background: #05080f;
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.h-message {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: #94a3b8;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}

	.h-error {
		color: #ef4444;
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
		border: 1px solid rgba(255, 255, 255, 0.08);
		background: #0a0e17;
	}

	.h-section-header {
		height: 24px;
		line-height: 24px;
		padding: 0 8px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
		color: #94a3b8;
		background: #0e1320;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		flex-shrink: 0;
	}

	.h-scroll-area {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow: y-auto;
	}

	/* Scrollbar minimalista */
	.h-scroll-area::-webkit-scrollbar {
		width: 4px;
		height: 4px;
	}
	.h-scroll-area::-webkit-scrollbar-track {
		background: transparent;
	}
	.h-scroll-area::-webkit-scrollbar-thumb {
		background: rgba(255, 255, 255, 0.1);
	}
	.h-scroll-area::-webkit-scrollbar-thumb:hover {
		background: rgba(255, 255, 255, 0.2);
	}

	.h-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		color: #cbd5e1;
	}

	.h-table th {
		position: sticky;
		top: 0;
		z-index: 20;
		background: #0e1320;
		color: #64748b;
		font-weight: 600;
		padding: 4px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		white-space: nowrap;
	}

	.h-table td {
		padding: 4px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
		white-space: nowrap;
	}

	.h-table tr:hover td {
		background: rgba(255, 255, 255, 0.02);
	}

	.text-left { text-align: left; }
	.text-right { text-align: right; }
</style>



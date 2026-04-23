<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber, formatPercent } from "@investintell/ui";
	import { createClientApiClient } from "../../../api/client";

	interface Props {
		fundId: string | null;
		ticker: string | null;
		label?: string;
	}

	let { fundId, ticker, label = "—" }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

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
		as_of?: string | null;
		disclosure?: {
			has_holdings?: boolean;
			message?: string | null;
		} | null;
	};

	let data = $state<HoldingsData | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		const currentFundId = fundId;
		if (!currentFundId) {
			data = null;
			error = null;
			loading = false;
			return;
		}

		let cancelled = false;

		async function fetchHoldings() {
			loading = true;
			error = null;
			try {
				const requestPath = `/wealth/discovery/funds/${encodeURIComponent(String(currentFundId))}/analysis/holdings/top`;
				const response = await api.get<HoldingsData>(
					requestPath,
				);
				if (cancelled) return;
				data = response;
			} catch (err: unknown) {
				if (cancelled) return;
				error = err instanceof Error ? err.message : "Failed to fetch holdings";
			} finally {
				if (cancelled) return;
				loading = false;
			}
		}

		void fetchHoldings();

		return () => {
			cancelled = true;
		};
	});

	function pctText(value: number | null | undefined): string {
		if (value == null) return "—";
		const decimal = Math.abs(value) > 1 ? value / 100 : value;
		return formatPercent(decimal, 2);
	}

	function moneyText(value: number | null | undefined): string {
		if (value == null) return "—";
		if (Math.abs(value) >= 1_000_000_000) return `$${formatNumber(value / 1_000_000_000, 2)}B`;
		if (Math.abs(value) >= 1_000_000) return `$${formatNumber(value / 1_000_000, 1)}M`;
		return `$${formatNumber(value, 0)}`;
	}

	function cleanLabel(value: string | null | undefined): string {
		if (!value) return "—";
		const normalized = value
			.replace(/[_/]+/g, " ")
			.replace(/\s+/g, " ")
			.trim();
		if (!normalized) return "—";
		const tokenMap: Record<string, string> = {
			ETF: "ETF",
			ADR: "ADR",
			REIT: "REIT",
			UCITS: "UCITS",
			NAV: "NAV",
			AUM: "AUM",
			CIK: "CIK",
			"13F": "13F",
			USA: "US",
			US: "US",
			EMEA: "EMEA",
			APAC: "APAC",
		};
		return normalized
			.split(" ")
			.map((word) => {
				const upper = word.toUpperCase();
				if (tokenMap[upper]) return tokenMap[upper];
				if (/^[A-Z0-9-]{2,}$/.test(word)) return upper;
				return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
			})
			.join(" ");
	}
</script>

<div class="h-root">
	<div class="h-header">
		<div class="h-headline">
			<span class="h-title">HOLDINGS INTELLIGENCE</span>
			<span class="h-subtitle">{ticker ?? "—"} · {cleanLabel(label)}</span>
		</div>
		{#if data?.as_of}
			<span class="h-asof">AS OF {data.as_of}</span>
		{/if}
	</div>
	{#if loading}
		<div class="h-message">Loading holdings...</div>
	{:else if error}
		<div class="h-message h-error">{error}</div>
	{:else if !data}
		<div class="h-message">No holdings data available.</div>
	{:else if data.top_holdings.length === 0 && data.sector_breakdown.length === 0}
		<div class="h-message">{data.disclosure?.message ?? "No holdings disclosure available."}</div>
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
									<td class="text-left td-primary">{cleanLabel(holding.issuer_name)}</td>
									<td class="text-left td-secondary">{cleanLabel(holding.sector)}</td>
									<td class="text-right">{pctText(holding.weight)}</td>
									<td class="text-right">{moneyText(holding.market_value)}</td>
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
											style="width: {Math.max(0, Math.min(100, (Math.abs(sector.weight) > 1 ? sector.weight : sector.weight * 100)))}%;"
										></div>
										<span class="sector-name">{cleanLabel(sector.name)}</span>
									</td>
									<td class="text-right">{sector.holdings_count}</td>
									<td class="text-right">{pctText(sector.weight)}</td>
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

	.h-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
		padding: 10px 12px 8px;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		flex-shrink: 0;
	}

	.h-headline {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}

	.h-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
	}

	.h-subtitle,
	.h-asof {
		color: var(--terminal-fg-muted);
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		font-variant-numeric: tabular-nums;
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

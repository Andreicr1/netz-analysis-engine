<!-- Holdings tab: quarter selector + paginated holdings with deltas -->
<script lang="ts">
	import { formatNumber, formatPercent, formatCompact, formatAUM } from "@netz/ui/utils";
	import type { SecHoldingsPage, SecReverseLookup } from "$lib/types/sec-analysis";
	import { EMPTY_HOLDINGS, EMPTY_REVERSE } from "$lib/types/sec-analysis";

	let {
		api,
		cik,
		managerName,
	}: {
		api: { get: <T>(url: string, params?: Record<string, string>) => Promise<T> };
		cik: string | null;
		managerName: string;
	} = $props();

	let holdings = $state<SecHoldingsPage>(EMPTY_HOLDINGS);
	let loading = $state(false);
	let selectedQuarter = $state<string | null>(null);
	let currentPage = $state(1);

	async function fetchHoldings() {
		if (!cik) return;
		loading = true;
		try {
			const params: Record<string, string> = {
				page: String(currentPage),
				page_size: "50",
			};
			if (selectedQuarter) params.quarter = selectedQuarter;
			holdings = await api.get<SecHoldingsPage>(
				`/sec/managers/${cik}/holdings`,
				params,
			);
			if (!selectedQuarter && holdings.quarter) {
				selectedQuarter = holdings.quarter;
			}
		} catch {
			holdings = EMPTY_HOLDINGS;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (cik) {
			currentPage = 1;
			selectedQuarter = null;
			fetchHoldings();
		}
	});

	function changeQuarter(q: string) {
		selectedQuarter = q;
		currentPage = 1;
		fetchHoldings();
	}

	function changePage(p: number) {
		currentPage = p;
		fetchHoldings();
	}

	let totalPages = $derived(
		Math.ceil(holdings.total_count / holdings.page_size) || 1,
	);

	// ── CUSIP Popover (C-02) ──
	let popoverCusip = $state<string | null>(null);
	let popoverData = $state<SecReverseLookup>(EMPTY_REVERSE);
	let popoverLoading = $state(false);
	let popoverCache = $state<Record<string, SecReverseLookup>>({});

	async function openCusipPopover(cusip: string) {
		if (popoverCusip === cusip) {
			popoverCusip = null;
			return;
		}
		popoverCusip = cusip;
		if (popoverCache[cusip]) {
			popoverData = popoverCache[cusip];
			return;
		}
		popoverLoading = true;
		try {
			const params: Record<string, string> = { cusip, limit: "10" };
			if (selectedQuarter) params.quarter = selectedQuarter;
			const data = await api.get<SecReverseLookup>("/sec/holdings/reverse", params);
			popoverData = data;
			popoverCache[cusip] = data;
		} catch {
			popoverData = EMPTY_REVERSE;
		} finally {
			popoverLoading = false;
		}
	}
</script>

{#if !cik}
	<div class="ht-empty">
		<p>Select a manager from the Overview tab to view holdings.</p>
	</div>
{:else}
	<div class="ht-header">
		<h3 class="ht-title">{managerName}</h3>
		{#if holdings.available_quarters.length > 0}
			<select
				class="ht-quarter-select"
				value={selectedQuarter}
				onchange={(e) => changeQuarter((e.target as HTMLSelectElement).value)}
			>
				{#each holdings.available_quarters as q}
					<option value={q}>{q}</option>
				{/each}
			</select>
		{/if}
	</div>

	{#if holdings.total_value != null}
		<div class="ht-summary">
			Total: {formatCompact(holdings.total_value)} USD
			&middot; {formatNumber(holdings.total_count, 0)} positions
		</div>
	{/if}

	{#if loading}
		<p class="ht-loading">Loading holdings...</p>
	{:else if holdings.holdings.length === 0}
		<div class="ht-empty"><p>No holdings found for this quarter.</p></div>
	{:else}
		<div class="ht-table-wrap">
			<table class="ht-table">
				<thead>
					<tr>
						<th class="ht-th">Company</th>
						<th class="ht-th">CUSIP</th>
						<th class="ht-th">Sector</th>
						<th class="ht-th ht-th--right">Shares</th>
						<th class="ht-th ht-th--right">Value ($)</th>
						<th class="ht-th ht-th--right">% Port</th>
						<th class="ht-th ht-th--right">Delta</th>
					</tr>
				</thead>
				<tbody>
					{#each holdings.holdings as h (h.cusip)}
						<tr class="ht-row">
							<td class="ht-td ht-td--name">{h.company_name}</td>
							<td class="ht-td ht-td--mono ht-td--cusip">
							<button
								class="ht-cusip-btn"
								onclick={(e) => { e.stopPropagation(); openCusipPopover(h.cusip); }}
								title="View holders"
							>
								{h.cusip}
							</button>
							{#if popoverCusip === h.cusip}
								<div class="ht-popover">
									{#if popoverLoading}
										<p class="ht-popover__loading">Loading holders...</p>
									{:else if popoverData.holders.length > 0}
										<div class="ht-popover__title">Top holders of {h.cusip}</div>
										<table class="ht-popover__table">
											<thead><tr><th>Firm</th><th>Shares</th><th>Value</th></tr></thead>
											<tbody>
												{#each popoverData.holders.slice(0, 10) as holder}
													<tr>
														<td>{holder.firm_name}</td>
														<td class="ht-popover__num">{holder.shares != null ? formatCompact(holder.shares) : "�"}</td>
														<td class="ht-popover__num">{holder.market_value != null ? formatCompact(holder.market_value) : "�"}</td>
													</tr>
												{/each}
											</tbody>
										</table>
										{#if popoverData.total_holders > 10}
											<div class="ht-popover__more">{popoverData.total_holders} holders total</div>
										{/if}
									{:else}
										<p class="ht-popover__loading">No holders found.</p>
									{/if}
								</div>
							{/if}
						</td>
							<td class="ht-td">{h.sector ?? "—"}</td>
							<td class="ht-td ht-td--right">
								{h.shares != null ? formatNumber(h.shares, 0) : "—"}
							</td>
							<td class="ht-td ht-td--right">
								{h.market_value != null ? formatCompact(h.market_value) : "—"}
							</td>
							<td class="ht-td ht-td--right">
								{h.pct_portfolio != null ? formatPercent(h.pct_portfolio) : "—"}
							</td>
							<td class="ht-td ht-td--right">
								{#if h.delta_action}
									<span
										class="ht-delta"
										class:ht-delta--up={h.delta_action === "NEW_POSITION" || h.delta_action === "INCREASED"}
										class:ht-delta--down={h.delta_action === "EXITED" || h.delta_action === "DECREASED"}
									>
										{h.delta_action === "NEW_POSITION" ? "NEW" :
										 h.delta_action === "EXITED" ? "EXIT" :
										 h.delta_shares != null ? formatNumber(h.delta_shares, 0) : h.delta_action}
									</span>
								{:else}
									—
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="ht-pagination">
			<button class="ht-page-btn" disabled={currentPage <= 1} onclick={() => changePage(currentPage - 1)}>Prev</button>
			<span class="ht-page-info">{currentPage} / {totalPages}</span>
			<button class="ht-page-btn" disabled={!holdings.has_next} onclick={() => changePage(currentPage + 1)}>Next</button>
		</div>
	{/if}
{/if}

<style>
	.ht-empty {
		padding: 48px 24px;
		text-align: center;
		color: var(--netz-text-muted);
		font-size: 14px;
	}
	.ht-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 0;
	}
	.ht-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--netz-text-primary);
	}
	.ht-quarter-select {
		padding: 4px 8px;
		font-size: 12px;
		border: 1px solid var(--netz-border-subtle);
		border-radius: 4px;
		background: var(--netz-surface-primary);
		color: var(--netz-text-primary);
	}
	.ht-summary {
		font-size: 12px;
		color: var(--netz-text-muted);
		padding-bottom: 8px;
	}
	.ht-loading {
		padding: 24px;
		color: var(--netz-text-muted);
		font-size: 13px;
	}
	.ht-table-wrap {
		overflow-x: auto;
	}
	.ht-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	.ht-th {
		padding: 8px 12px;
		text-align: left;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		border-bottom: 1px solid var(--netz-border-subtle);
		white-space: nowrap;
	}
	.ht-th--right {
		text-align: right;
	}
	.ht-row {
		transition: background 120ms ease;
	}
	.ht-row:hover {
		background: var(--netz-surface-secondary);
	}
	.ht-td {
		padding: 8px 12px;
		border-bottom: 1px solid var(--netz-border-subtle);
		white-space: nowrap;
	}
	.ht-td--name {
		max-width: 240px;
		overflow: hidden;
		text-overflow: ellipsis;
		font-weight: 500;
	}
	.ht-td--mono {
		font-family: "IBM Plex Mono", monospace;
		font-size: 12px;
	}
	.ht-td--right {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.ht-delta {
		font-size: 11px;
		font-weight: 600;
	}
	.ht-delta--up {
		color: var(--netz-color-success, #22c55e);
	}
	.ht-delta--down {
		color: var(--netz-color-error, #ef4444);
	}
	.ht-pagination {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 12px;
		padding: 12px 0;
	}
	.ht-page-btn {
		padding: 4px 12px;
		font-size: 12px;
		border: 1px solid var(--netz-border-subtle);
		border-radius: 4px;
		background: var(--netz-surface-primary);
		color: var(--netz-text-primary);
		cursor: pointer;
	}
	.ht-page-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.ht-page-info {
		font-size: 12px;
		color: var(--netz-text-muted);
	}

	/* CUSIP Popover */
	.ht-td--cusip {
		position: relative;
	}
	.ht-cusip-btn {
		background: none;
		border: none;
		padding: 0;
		font-family: "IBM Plex Mono", monospace;
		font-size: 12px;
		color: var(--netz-brand-primary);
		cursor: pointer;
		text-decoration: underline;
		text-decoration-style: dotted;
	}
	.ht-cusip-btn:hover {
		text-decoration-style: solid;
	}
	.ht-popover {
		position: absolute;
		top: 100%;
		left: 0;
		z-index: 50;
		min-width: 360px;
		max-width: 480px;
		padding: 12px;
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
	}
	.ht-popover__title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		margin-bottom: 8px;
	}
	.ht-popover__loading {
		font-size: 12px;
		color: var(--netz-text-muted);
	}
	.ht-popover__table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.ht-popover__table th {
		text-align: left;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		padding: 4px 8px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}
	.ht-popover__table td {
		padding: 4px 8px;
		border-bottom: 1px solid color-mix(in srgb, var(--netz-border-subtle) 50%, transparent);
	}
	.ht-popover__num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.ht-popover__more {
		font-size: 11px;
		color: var(--netz-text-muted);
		text-align: right;
		margin-top: 6px;
	}
</style>

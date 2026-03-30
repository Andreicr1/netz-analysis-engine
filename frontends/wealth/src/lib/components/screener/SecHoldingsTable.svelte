<!-- SEC Holdings table with virtual scrolling for N-PORT funds (10k+ rows).
     Uses @tanstack/svelte-virtual for row virtualization.
     Holdings data is kept as raw (non-reactive) to avoid $state proxy overhead. -->
<script lang="ts">
	import { formatNumber, formatPercent, formatCompact } from "@investintell/ui";
	import { createVirtualizer } from "@tanstack/svelte-virtual";
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

	// ── Raw data (NOT $state — avoids deep proxy on 10k+ row arrays) ──
	let holdings: SecHoldingsPage = EMPTY_HOLDINGS;
	let loading = $state(false);
	let selectedQuarter = $state<string | null>(null);
	let dataVersion = $state(0); // bump to trigger re-render

	// ── Fetch holdings for the quarter (page_size=200 — backend max) ──
	async function fetchHoldings() {
		if (!cik) return;
		loading = true;
		try {
			const params: Record<string, string> = {
				page: "1",
				page_size: "200",
			};
			if (selectedQuarter) params.quarter = selectedQuarter;
			holdings = await api.get<SecHoldingsPage>(
				`/sec/managers/${cik}/holdings`,
				params,
			);
			if (!selectedQuarter && holdings.quarter) {
				selectedQuarter = holdings.quarter;
			}
			dataVersion++;
		} catch {
			holdings = EMPTY_HOLDINGS;
			dataVersion++;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (cik) {
			selectedQuarter = null;
			fetchHoldings();
		}
	});

	function changeQuarter(q: string) {
		selectedQuarter = q;
		fetchHoldings();
	}

	// ── Virtual scrolling ──
	let scrollContainerEl: HTMLDivElement | undefined = $state(undefined);

	const ROW_HEIGHT = 44;

	// Virtualizer store (Svelte integration returns a Readable<Virtualizer>)
	let virtualizerStore = $derived(
		scrollContainerEl
			? createVirtualizer({
					getScrollElement: () => scrollContainerEl!,
					count: holdings.holdings.length,
					estimateSize: () => ROW_HEIGHT,
					overscan: 15,
				})
			: null,
	);

	// Subscribe to the store for reactive updates
	let virt: { getVirtualItems: () => Array<{ index: number; start: number }>; getTotalSize: () => number } | null = $state(null);

	$effect(() => {
		if (!virtualizerStore) { virt = null; return; }
		const unsub = virtualizerStore.subscribe((v) => { virt = v as any; });
		return unsub;
	});

	// ── CUSIP Popover ──
	let popoverCusip = $state<string | null>(null);
	let popoverData = $state<SecReverseLookup>(EMPTY_REVERSE);
	let popoverLoading = $state(false);
	let popoverCache: Record<string, SecReverseLookup> = {};

	async function openCusipPopover(cusip: string) {
		if (popoverCusip === cusip) { popoverCusip = null; return; }
		popoverCusip = cusip;
		if (popoverCache[cusip]) { popoverData = popoverCache[cusip]; return; }
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
	<div class="ht-empty"><p>Select a fund with holdings disclosure to view positions.</p></div>
{:else}
	<div class="ht-header">
		<h3 class="ht-title">{managerName}</h3>
		{#if holdings.available_quarters.length > 0}
			<select class="ht-quarter-select" value={selectedQuarter}
				onchange={(e) => changeQuarter((e.target as HTMLSelectElement).value)}>
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
			{#if holdings.holdings.length < holdings.total_count}
				&middot; Showing {holdings.holdings.length} of {holdings.total_count}
			{/if}
		</div>
	{/if}

	{#if loading}
		<p class="ht-loading">Loading holdings...</p>
	{:else if holdings.holdings.length === 0}
		<div class="ht-empty"><p>No holdings found for this quarter.</p></div>
	{:else}
		<!-- Sticky header -->
		<div class="ht-table-header">
			<table class="ht-table">
				<thead>
					<tr>
						<th class="ht-th" style="width:220px">Company</th>
						<th class="ht-th" style="width:100px">CUSIP</th>
						<th class="ht-th" style="width:120px">Sector</th>
						<th class="ht-th ht-th--right" style="width:100px">Shares</th>
						<th class="ht-th ht-th--right" style="width:100px">Value ($)</th>
						<th class="ht-th ht-th--right" style="width:80px">% Port</th>
						<th class="ht-th ht-th--right" style="width:80px">Delta</th>
					</tr>
				</thead>
			</table>
		</div>

		<!-- Virtualized scroll container -->
		<div class="ht-virtual-container" bind:this={scrollContainerEl}>
			{#if virt}
				{@const items = virt.getVirtualItems()}
				<div class="ht-virtual-spacer" style="height: {virt.getTotalSize()}px;">
					<table class="ht-table ht-table--body" style="transform: translateY({items[0]?.start ?? 0}px);">
						<tbody>
							{#each items as vRow (vRow.index)}
								{@const h = holdings.holdings[vRow.index]!}
								<tr class="ht-row" style="height: {ROW_HEIGHT}px;">
									<td class="ht-td ht-td--name" style="width:220px">{h.company_name}</td>
									<td class="ht-td ht-td--mono ht-td--cusip" style="width:100px">
										<button class="ht-cusip-btn"
											onclick={(e) => { e.stopPropagation(); openCusipPopover(h.cusip); }}
											title="View holders">
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
																	<td class="ht-popover__num">{holder.shares != null ? formatCompact(holder.shares) : "\u2014"}</td>
																	<td class="ht-popover__num">{holder.market_value != null ? formatCompact(holder.market_value) : "\u2014"}</td>
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
									<td class="ht-td" style="width:120px">{h.sector ?? "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:100px">{h.shares != null ? formatNumber(h.shares, 0) : "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:100px">{h.market_value != null ? formatCompact(h.market_value) : "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:80px">{h.pct_portfolio != null ? formatPercent(h.pct_portfolio) : "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:80px">
										{#if h.delta_action}
											<span class="ht-delta"
												class:ht-delta--up={h.delta_action === "NEW_POSITION" || h.delta_action === "INCREASED"}
												class:ht-delta--down={h.delta_action === "EXITED" || h.delta_action === "DECREASED"}>
												{h.delta_action === "NEW_POSITION" ? "NEW" : h.delta_action === "EXITED" ? "EXIT" : h.delta_shares != null ? formatNumber(h.delta_shares, 0) : h.delta_action}
											</span>
										{:else}
											\u2014
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<!-- Load more if server has more pages -->
		{#if holdings.has_next}
			<div class="ht-load-more">
				<span class="ht-load-hint">Showing {holdings.holdings.length} of {holdings.total_count} positions</span>
			</div>
		{/if}
	{/if}
{/if}

<style>
	.ht-empty { padding: 48px 24px; text-align: center; color: var(--ii-text-muted); font-size: 14px; }
	.ht-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; }
	.ht-title { font-size: 15px; font-weight: 600; color: var(--ii-text-primary); }
	.ht-quarter-select { padding: 4px 8px; font-size: 12px; border: 1px solid var(--ii-border-subtle); border-radius: 4px; background: var(--ii-surface-primary); color: var(--ii-text-primary); }
	.ht-summary { font-size: 12px; color: var(--ii-text-muted); padding-bottom: 8px; }
	.ht-loading { padding: 24px; color: var(--ii-text-muted); font-size: 13px; }

	/* Sticky header */
	.ht-table-header { overflow: hidden; border-bottom: 1px solid var(--ii-border-subtle); }

	/* Virtual scroll container */
	.ht-virtual-container { max-height: 520px; overflow-y: auto; overflow-x: auto; }
	.ht-virtual-spacer { position: relative; width: 100%; }
	.ht-table--body { position: absolute; top: 0; left: 0; width: 100%; }

	.ht-table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
	.ht-th {
		padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600;
		text-transform: uppercase; letter-spacing: 0.04em; color: var(--ii-text-muted);
		white-space: nowrap; background: #f8fafc;
	}
	.ht-th--right { text-align: right; }
	.ht-row { transition: background 120ms ease; }
	.ht-row:hover { background: var(--ii-surface-secondary); }
	.ht-td { padding: 8px 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
	.ht-td--name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
	.ht-td--mono { font-family: "IBM Plex Mono", monospace; font-size: 12px; }
	.ht-td--right { text-align: right; font-variant-numeric: tabular-nums; }
	.ht-delta { font-size: 11px; font-weight: 600; }
	.ht-delta--up { color: var(--ii-color-success, #22c55e); }
	.ht-delta--down { color: var(--ii-color-error, #ef4444); }

	.ht-load-more { padding: 12px; text-align: center; }
	.ht-load-hint { font-size: 12px; color: var(--ii-text-muted); }

	.ht-td--cusip { position: relative; }
	.ht-cusip-btn {
		background: none; border: none; padding: 0; font-family: "IBM Plex Mono", monospace;
		font-size: 12px; color: var(--ii-brand-primary); cursor: pointer;
		text-decoration: underline; text-decoration-style: dotted;
	}
	.ht-cusip-btn:hover { text-decoration-style: solid; }
	.ht-popover {
		position: absolute; top: 100%; left: 0; z-index: 50; min-width: 360px; max-width: 480px;
		padding: 12px; background: var(--ii-surface-elevated); border: 1px solid var(--ii-border-subtle);
		border-radius: 10px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
	}
	.ht-popover__title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ii-text-muted); margin-bottom: 8px; }
	.ht-popover__loading { font-size: 12px; color: var(--ii-text-muted); }
	.ht-popover__table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.ht-popover__table th { text-align: left; font-size: 10px; font-weight: 600; text-transform: uppercase; color: var(--ii-text-muted); padding: 4px 8px; border-bottom: 1px solid var(--ii-border-subtle); }
	.ht-popover__table td { padding: 4px 8px; border-bottom: 1px solid color-mix(in srgb, var(--ii-border-subtle) 50%, transparent); }
	.ht-popover__num { text-align: right; font-variant-numeric: tabular-nums; }
	.ht-popover__more { font-size: 11px; color: var(--ii-text-muted); text-align: right; margin-top: 6px; }
</style>

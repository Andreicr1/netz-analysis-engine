<!-- N-PORT Holdings table with virtual scrolling for registered funds.
     Uses @tanstack/svelte-virtual for row virtualization.
     Holdings data is kept as raw (non-reactive) to avoid $state proxy overhead. -->
<script lang="ts">
	import { formatNumber, formatPercent, formatCompact } from "@investintell/ui";
	import { createVirtualizer } from "@tanstack/svelte-virtual";
	import type { NportHoldingsPage } from "$lib/types/sec-funds";
	import { EMPTY_HOLDINGS } from "$lib/types/sec-funds";

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
	let holdings: NportHoldingsPage = EMPTY_HOLDINGS;
	let loading = $state(false);
	let selectedQuarter = $state<string | null>(null);
	let dataVersion = $state(0); // bump to trigger re-render

	// ── Fetch N-PORT holdings for the quarter ──
	async function fetchHoldings() {
		if (!cik) return;
		loading = true;
		try {
			const params: Record<string, string> = {
				limit: "200",
				offset: "0",
			};
			if (selectedQuarter) params.quarter = selectedQuarter;
			holdings = await api.get<NportHoldingsPage>(
				`/sec/funds/${cik}/holdings`,
				params,
			);
			if (!selectedQuarter && holdings.available_quarters.length > 0) {
				selectedQuarter = holdings.available_quarters[0] ?? null;
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

	let virt: { getVirtualItems: () => Array<{ index: number; start: number }>; getTotalSize: () => number } | null = $state(null);

	$effect(() => {
		if (!virtualizerStore) { virt = null; return; }
		const unsub = virtualizerStore.subscribe((v) => { virt = v as any; });
		return unsub;
	});
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
						<th class="ht-th" style="width:220px">Issuer</th>
						<th class="ht-th" style="width:100px">CUSIP</th>
						<th class="ht-th" style="width:100px">Asset Class</th>
						<th class="ht-th" style="width:100px">Sector</th>
						<th class="ht-th ht-th--right" style="width:100px">Quantity</th>
						<th class="ht-th ht-th--right" style="width:100px">Mkt Value</th>
						<th class="ht-th ht-th--right" style="width:80px">% NAV</th>
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
									<td class="ht-td ht-td--name" style="width:220px">{h.issuer_name ?? "\u2014"}</td>
									<td class="ht-td ht-td--mono" style="width:100px">{h.cusip ?? h.isin ?? "\u2014"}</td>
									<td class="ht-td" style="width:100px">{h.asset_class ?? "\u2014"}</td>
									<td class="ht-td" style="width:100px">{h.sector ?? "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:100px">{h.quantity != null ? formatNumber(h.quantity, 0) : "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:100px">{h.market_value != null ? formatCompact(h.market_value) : "\u2014"}</td>
									<td class="ht-td ht-td--right" style="width:80px">{h.pct_of_nav != null ? formatPercent(h.pct_of_nav) : "\u2014"}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
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
		white-space: nowrap; background: var(--ii-surface-alt, #f8fafc);
	}
	.ht-th--right { text-align: right; }
	.ht-row { transition: background 120ms ease; }
	.ht-row:hover { background: var(--ii-surface-secondary); }
	.ht-td { padding: 8px 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
	.ht-td--name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
	.ht-td--mono { font-family: "IBM Plex Mono", monospace; font-size: 12px; }
	.ht-td--right { text-align: right; font-variant-numeric: tabular-nums; }
</style>

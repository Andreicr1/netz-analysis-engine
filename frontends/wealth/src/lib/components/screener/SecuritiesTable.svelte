<!--
  Global Securities table — queries sec_cusip_ticker_map (no RLS).
  Server-side pagination. Columns: Ticker, Name, Type, Exchange, CUSIP.
-->
<script lang="ts">
	import "./screener.css";
	import type { SecurityItem, SecurityPage } from "$lib/types/catalog";
	import { EMPTY_SECURITY_PAGE } from "$lib/types/catalog";

	interface Props {
		securities: SecurityPage;
		searchQ: string;
		onSelectSecurity: (item: SecurityItem) => void;
		onPageChange: (page: number) => void;
	}

	let { securities = EMPTY_SECURITY_PAGE, searchQ = "", onSelectSecurity, onPageChange }: Props = $props();

	let totalPages = $derived(Math.ceil(securities.total / securities.page_size) || 1);

	function typeLabel(st: string): string {
		const m: Record<string, string> = {
			"Common Stock": "Stock",
			"ETP": "ETF",
			"Closed-End Fund": "CEF",
			"Open-End Fund": "OEF",
			"ADR": "ADR",
			"REIT": "REIT",
			"MLP": "MLP",
		};
		return m[st] ?? st;
	}
</script>

<div class="scr-data-header">
	<span class="scr-data-count">
		Securities
		<span class="scr-count-badge">{securities.total.toLocaleString()} GLOBAL</span>
	</span>
	{#if searchQ}
		<span class="scr-data-count-muted">matching "{searchQ}"</span>
	{/if}
	<span class="st-page-label">Page {securities.page} of {totalPages}</span>
</div>

{#if securities.items.length === 0}
	<div class="scr-empty">No securities found. Adjust filters or search.</div>
{:else}
	<div class="scr-table-wrap">
		<table class="scr-table">
			<thead>
				<tr>
					<th>Ticker</th>
					<th class="sth-name">Name</th>
					<th>Type</th>
					<th>Exchange</th>
					<th>CUSIP</th>
				</tr>
			</thead>
			<tbody>
				{#each securities.items as item (item.cusip)}
					<tr class="scr-inst-row" onclick={() => onSelectSecurity(item)}>
						<td class="std-ticker">
							<span class="ticker-cell">{item.ticker ?? "\u2014"}</span>
						</td>
						<td class="std-name">
							<span class="inst-name">{item.name}</span>
						</td>
						<td>
							<span class="st-type-badge st-type-badge--{item.asset_class}">{typeLabel(item.security_type)}</span>
						</td>
						<td class="st-exchange">{item.exchange ?? "\u2014"}</td>
						<td class="st-cusip">{item.cusip}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<div class="scr-pagination">
		<button class="scr-page-btn" disabled={securities.page <= 1} onclick={() => onPageChange(securities.page - 1)}>Prev</button>
		<span class="scr-page-info">{securities.page} / {totalPages}</span>
		<button class="scr-page-btn" disabled={!securities.has_next} onclick={() => onPageChange(securities.page + 1)}>Next</button>
	</div>
{/if}

<style>
	.st-page-label { margin-left: auto; font-size: 12px; color: #90a1b9; font-variant-numeric: tabular-nums; }
	.ticker-cell { font-weight: 700; font-size: 13px; letter-spacing: 0.3px; color: var(--ii-text-primary, #1a202c); }
	.inst-name { display: block; font-weight: 600; font-size: 14px; color: #1d293d; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.st-exchange { color: #62748e; font-size: 13px; }
	.st-cusip { font-family: Consolas, var(--ii-font-mono, monospace); font-size: 12px; color: #62748e; }
	.st-type-badge { display: inline-block; padding: 3px 8px; border-radius: 8px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
	.st-type-badge--equity { background: #eff6ff; border: 1px solid #dbeafe; color: #1447e6; }
	.st-type-badge--real_estate { background: #fef9ec; border: 1px solid #fde68a; color: #b45309; }
	.scr-count-badge { display: inline-flex; align-items: center; padding: 3px 10px; background: #ecfdf5; border-radius: 8px; font-size: 11px; font-weight: 700; color: #059669; text-transform: uppercase; letter-spacing: 0.55px; }
</style>

<!--
  Server-side paginated catalog table for UnifiedFundItem[].
  No infinite scroll — clean Prev/Next pagination synced with URL params.
-->
<script lang="ts">
	import "./screener.css";
	import { formatAUM } from "@netz/ui";
	import type { UnifiedFundItem, UnifiedCatalogPage } from "$lib/types/catalog";
	import { EMPTY_CATALOG_PAGE, UNIVERSE_LABELS } from "$lib/types/catalog";

	interface Props {
		catalog: UnifiedCatalogPage;
		searchQ: string;
		onSelectFund: (item: UnifiedFundItem) => void;
		onPageChange: (page: number) => void;
	}

	let { catalog = EMPTY_CATALOG_PAGE, searchQ = "", onSelectFund, onPageChange }: Props = $props();

	let totalPages = $derived(Math.ceil(catalog.total / catalog.page_size) || 1);

	function universeBadgeClass(universe: string): string {
		switch (universe) {
			case "registered_us": return "univ-badge--registered";
			case "private_us": return "univ-badge--private";
			case "ucits_eu": return "univ-badge--ucits";
			default: return "";
		}
	}

	function fundTypeLabel(ft: string): string {
		return ft.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}
</script>

<div class="scr-data-header">
	<span class="scr-data-count">
		Catalog
		<span class="scr-count-badge">{catalog.total.toLocaleString()} FUND{catalog.total !== 1 ? "S" : ""}</span>
	</span>
	{#if searchQ}
		<span class="scr-data-count-muted">matching "{searchQ}"</span>
	{/if}
	<span class="ct-page-label">
		Page {catalog.page} of {totalPages}
	</span>
</div>

{#if catalog.items.length === 0}
	<div class="scr-empty">No funds found. Adjust filters or search.</div>
{:else}
	<div class="scr-table-wrap">
		<table class="scr-table">
			<thead>
				<tr>
					<th class="sth-univ">Universe</th>
					<th>Ticker</th>
					<th class="sth-name">Name</th>
					<th>Manager</th>
					<th>Type</th>
					<th class="sth-aum">AUM</th>
					<th>Region</th>
					<th>Disclosure</th>
				</tr>
			</thead>
			<tbody>
				{#each catalog.items as item (`${item.universe}:${item.external_id}`)}
					<tr class="scr-inst-row" onclick={() => onSelectFund(item)}>
						<td>
							<span class="univ-badge {universeBadgeClass(item.universe)}">
								{UNIVERSE_LABELS[item.universe] ?? item.universe}
							</span>
						</td>
						<td class="std-ticker">
							<span class="ticker-cell">{item.ticker ?? "\u2014"}</span>
						</td>
						<td class="std-name">
							<span class="inst-name">{item.name}</span>
							{#if item.isin}
								<span class="inst-ids">{item.isin}</span>
							{/if}
						</td>
						<td class="std-manager">{item.manager_name ?? "\u2014"}</td>
						<td>
							<span class="ct-type-label">{fundTypeLabel(item.fund_type)}</span>
						</td>
						<td class="std-aum">{item.aum ? formatAUM(item.aum) : "\u2014"}</td>
						<td>{item.region}</td>
						<td>
							<div class="ct-disclosure-dots">
								<span class="ct-dot" class:ct-dot--on={item.disclosure.has_holdings} title="Holdings"></span>
								<span class="ct-dot" class:ct-dot--on={item.disclosure.has_nav_history} title="NAV"></span>
								<span class="ct-dot" class:ct-dot--on={item.disclosure.has_quant_metrics} title="Quant"></span>
								<span class="ct-dot" class:ct-dot--on={item.disclosure.has_style_analysis} title="Style"></span>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Server-side pagination -->
	<div class="scr-pagination">
		<button class="scr-page-btn" disabled={catalog.page <= 1} onclick={() => onPageChange(catalog.page - 1)}>
			Prev
		</button>
		<span class="scr-page-info">
			{catalog.page} / {totalPages}
		</span>
		<button class="scr-page-btn" disabled={!catalog.has_next} onclick={() => onPageChange(catalog.page + 1)}>
			Next
		</button>
	</div>
{/if}

<style>
	.ct-page-label {
		margin-left: auto;
		font-size: 12px;
		color: #90a1b9;
		font-variant-numeric: tabular-nums;
	}

	.ticker-cell {
		font-weight: 700;
		font-size: 13px;
		letter-spacing: 0.3px;
		color: var(--netz-text-primary, #1a202c);
	}

	.inst-name {
		display: block;
		font-weight: 600;
		font-size: 14px;
		color: #1d293d;
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.inst-ids {
		display: inline-block;
		font-size: 11px;
		color: #62748e;
		font-family: Consolas, var(--netz-font-mono, monospace);
		background: #f1f5f9;
		border-radius: 4px;
		padding: 1px 6px;
		margin-top: 4px;
	}

	/* Universe badges */
	.univ-badge {
		display: inline-block;
		padding: 3px 8px;
		border-radius: 8px;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		white-space: nowrap;
	}

	.univ-badge--registered {
		background: #fff7ed;
		border: 1px solid #fed7aa;
		color: #c2410c;
	}

	.univ-badge--private {
		background: #fef2f2;
		border: 1px solid #fecaca;
		color: #dc2626;
	}

	.univ-badge--ucits {
		background: #ecfdf5;
		border: 1px solid #d0fae5;
		color: #007a55;
	}

	.ct-type-label {
		font-size: 12px;
		color: #62748e;
		font-weight: 500;
		white-space: nowrap;
	}

	/* Disclosure dots */
	.ct-disclosure-dots {
		display: flex;
		gap: 4px;
		align-items: center;
	}

	.ct-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: #e2e8f0;
		flex-shrink: 0;
	}

	.ct-dot--on {
		background: #22c55e;
	}

	.scr-count-badge {
		display: inline-flex;
		align-items: center;
		padding: 3px 10px;
		background: #eff6ff;
		border-radius: 8px;
		font-size: 11px;
		font-weight: 700;
		color: #1447e6;
		text-transform: uppercase;
		letter-spacing: 0.55px;
	}
</style>

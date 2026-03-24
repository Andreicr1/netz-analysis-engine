<!--
  Holdings/NPort tab — paginated N-PORT holdings merged with latest data.
  Lazy-loaded with server-side pagination.
-->
<script lang="ts">
	import "./screener.css";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { formatAUM, formatPercent, formatDate } from "@netz/ui";
	import type { NportHoldingsResponse } from "$lib/types/manager-screener";

	interface Props {
		crd: string | null;
	}

	let { crd }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<NportHoldingsResponse | null>(null);
	let currentPage = $state(1);
	const PAGE_SIZE = 50;

	$effect(() => {
		if (!crd) {
			data = null;
			return;
		}

		const currentCrd = crd;
		const controller = new AbortController();
		currentPage = 1;

		fetchHoldings(currentCrd, 1, controller);

		return () => controller.abort();
	});

	async function fetchHoldings(targetCrd: string, page: number, controller?: AbortController) {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.get<NportHoldingsResponse>(
				`/manager-screener/managers/${targetCrd}/nport`,
				{ page: String(page), page_size: String(PAGE_SIZE) },
			);
			if (!controller?.signal.aborted) {
				data = result;
				currentPage = page;
			}
		} catch (e) {
			if (!controller?.signal.aborted) {
				error = e instanceof Error ? e.message : "Failed to load holdings";
			}
		} finally {
			if (!controller?.signal.aborted) {
				loading = false;
			}
		}
	}

	function goToPage(page: number) {
		if (!crd) return;
		fetchHoldings(crd, page);
	}

	function retry() {
		if (!crd) return;
		fetchHoldings(crd, currentPage);
	}
</script>

{#if !crd}
	<div class="dt-section">
		<p class="dt-empty-text">Institutional data unavailable — This manager is not registered with the SEC.</p>
	</div>
{:else if loading}
	<div class="dt-loading">Loading holdings…</div>
{:else if error}
	<div class="dt-section">
		<p class="dt-empty-text" style="color: var(--netz-danger)">{error}</p>
		<button class="scr-page-btn" onclick={retry}>Retry</button>
	</div>
{:else if data && data.total_holdings > 0}
	{#if data.report_date}
		<div class="holdings-header">
			<span class="holdings-report-date">Report date: {formatDate(data.report_date)}</span>
			<span class="holdings-total">{data.total_holdings} holdings</span>
		</div>
	{/if}

	<div class="scr-table-wrap">
		<table class="criteria-table">
			<thead>
				<tr>
					<th>Issuer</th>
					<th>Sector</th>
					<th style="text-align:right">Market Value</th>
					<th style="text-align:right">% NAV</th>
					<th>Currency</th>
				</tr>
			</thead>
			<tbody>
				{#each data.holdings as h (h.cusip ?? h.isin ?? h.issuer_name)}
					<tr>
						<td class="criteria-name">
							{h.issuer_name}
							{#if h.isin}
								<span class="holdings-isin">{h.isin}</span>
							{/if}
						</td>
						<td class="criteria-val">{h.sector ?? "—"}</td>
						<td class="criteria-val" style="text-align:right">{h.market_value ? formatAUM(h.market_value) : "—"}</td>
						<td class="criteria-val" style="text-align:right">{h.pct_of_nav ? formatPercent(h.pct_of_nav / 100) : "—"}</td>
						<td class="criteria-val">{h.currency ?? "—"}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if data.total_pages > 1}
		<div class="scr-pagination">
			<button class="scr-page-btn" disabled={currentPage <= 1} onclick={() => goToPage(currentPage - 1)}>Previous</button>
			<span class="scr-page-info">Page {currentPage} of {data.total_pages}</span>
			<button class="scr-page-btn" disabled={currentPage >= data.total_pages} onclick={() => goToPage(currentPage + 1)}>Next</button>
		</div>
	{/if}
{:else if data && data.total_holdings === 0}
	<div class="dt-empty">No holdings on record. Coverage updates quarterly.</div>
{:else}
	<div class="dt-empty">No holdings data available.</div>
{/if}

<style>
	.holdings-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.holdings-report-date {
		color: var(--netz-text-secondary);
	}

	.holdings-total {
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.holdings-isin {
		display: block;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		font-family: var(--netz-font-mono);
	}
</style>

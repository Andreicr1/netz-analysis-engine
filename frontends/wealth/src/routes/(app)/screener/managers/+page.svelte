<!--
  Manager Screener List — paginated table with text search, compare (max 3).
  Route: /screener/managers
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { formatAUM, ContextPanel } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ScreenerPage, ManagerRow, CompareResult } from "$lib/types/manager-screener";
	import { EMPTY_SCREENER } from "$lib/types/manager-screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let { data }: { data: PageData } = $props();

	const initParams = (data.currentParams as Record<string, string>) ?? {};
	let managers = $derived((data.managers ?? EMPTY_SCREENER) as ScreenerPage);

	// ── Search ──
	let searchQ = $state(initParams.q ?? "");
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	function applyFilters(page = 1) {
		const params = new URLSearchParams();
		if (searchQ) params.set("q", searchQ);
		params.set("page", String(page));
		params.set("page_size", "25");
		goto(`/screener/managers?${params.toString()}`, { invalidateAll: true });
	}

	function debouncedSearch() {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => applyFilters(), 400);
	}

	function handleSearchKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") {
			if (debounceTimer) clearTimeout(debounceTimer);
			applyFilters();
		}
	}

	// ── Pagination ──
	function goPage(p: number) {
		applyFilters(p);
	}

	// ── Compare ──
	let selectedCrds = $state<string[]>([]);
	let compareOpen = $state(false);
	let compareLoading = $state(false);
	let compareResult = $state<CompareResult | null>(null);

	function toggleSelect(crd: string) {
		if (selectedCrds.includes(crd)) {
			selectedCrds = selectedCrds.filter((c) => c !== crd);
		} else if (selectedCrds.length < 3) {
			selectedCrds = [...selectedCrds, crd];
		}
	}

	async function runCompare() {
		if (selectedCrds.length < 2) return;
		compareLoading = true;
		compareResult = null;
		compareOpen = true;
		try {
			compareResult = await api.post<CompareResult>(
				"/manager-screener/managers/compare",
				{ crd_numbers: selectedCrds },
			);
		} catch {
			compareResult = null;
		} finally {
			compareLoading = false;
		}
	}
</script>

<svelte:head>
	<title>Manager Screener — Netz Wealth</title>
</svelte:head>

<div class="mgrs-page">
	<!-- ════════════════ HEADER ════════════════ -->
	<div class="mgrs-topbar">
		<div class="mgrs-topbar-left">
			<a href="/screener" class="mgrs-back">&larr; Fund Screener</a>
			<h1 class="mgrs-title">Manager Screener</h1>
		</div>
		<div class="mgrs-topbar-right">
			{#if selectedCrds.length >= 2}
				<button class="mgrs-btn mgrs-btn--primary" onclick={runCompare}>
					Compare ({selectedCrds.length})
				</button>
			{/if}
		</div>
	</div>

	<!-- ════════════════ SEARCH BAR ════════════════ -->
	<div class="mgrs-filterbar">
		<input
			class="mgrs-search"
			type="text"
			placeholder="Search by name or CRD..."
			bind:value={searchQ}
			oninput={debouncedSearch}
			onkeydown={handleSearchKeydown}
		/>
		<span class="mgrs-count">{managers.total_count.toLocaleString()} managers</span>
	</div>

	<!-- ════════════════ TABLE ════════════════ -->
	<div class="mgrs-table-card">
		<div class="mgrs-table-scroll">
			<table class="mgrs-table">
				<thead>
					<tr>
						<th class="mgrs-th mgrs-th--check"></th>
						<th class="mgrs-th">Manager</th>
						<th class="mgrs-th">CRD</th>
						<th class="mgrs-th mgrs-th--right">AUM</th>
						<th class="mgrs-th">State</th>
						<th class="mgrs-th mgrs-th--right">Holdings</th>
						<th class="mgrs-th">Status</th>
						<th class="mgrs-th mgrs-th--action"></th>
					</tr>
				</thead>
				<tbody>
					{#each managers.managers as mgr (mgr.crd_number)}
						{@const checked = selectedCrds.includes(mgr.crd_number)}
						<tr class="mgrs-row" class:mgrs-row--selected={checked}>
							<td class="mgrs-td mgrs-td--check">
								<input
									type="checkbox"
									{checked}
									disabled={!checked && selectedCrds.length >= 3}
									onchange={() => toggleSelect(mgr.crd_number)}
								/>
							</td>
							<td class="mgrs-td mgrs-td--name">
								<button class="mgrs-name-link" onclick={() => goto(`/screener/managers/${mgr.crd_number}`)}>
									{mgr.firm_name}
								</button>
							</td>
							<td class="mgrs-td mgrs-td--mono">{mgr.crd_number}</td>
							<td class="mgrs-td mgrs-td--right">{mgr.aum_total != null ? formatAUM(mgr.aum_total) : "\u2014"}</td>
							<td class="mgrs-td">{mgr.state ?? "\u2014"}</td>
							<td class="mgrs-td mgrs-td--right">{mgr.position_count ?? "\u2014"}</td>
							<td class="mgrs-td">
								{#if mgr.universe_status}
									<span class="mgrs-badge mgrs-badge--{mgr.universe_status}">{mgr.universe_status}</span>
								{:else}
									<span class="mgrs-badge mgrs-badge--none">—</span>
								{/if}
							</td>
							<td class="mgrs-td mgrs-td--action">
								<a href="/screener/managers/{mgr.crd_number}" class="mgrs-view-link">View</a>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="8" class="mgrs-td mgrs-empty">
								{searchQ ? "No managers match your search." : "No managers found."}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Pagination -->
		{#if managers.total_count > 0}
			<div class="mgrs-pagination">
				<button
					class="mgrs-page-btn"
					disabled={managers.page <= 1}
					onclick={() => goPage(managers.page - 1)}
				>&larr; Previous</button>
				<span class="mgrs-page-info">
					Page {managers.page} of {Math.ceil(managers.total_count / managers.page_size)}
				</span>
				<button
					class="mgrs-page-btn"
					disabled={!managers.has_next}
					onclick={() => goPage(managers.page + 1)}
				>Next &rarr;</button>
			</div>
		{/if}
	</div>
</div>

<!-- ════════════════ COMPARE PANEL ════════════════ -->
<ContextPanel open={compareOpen} onClose={() => (compareOpen = false)} title="Manager Comparison" width="min(70vw, 900px)">
	{#if compareLoading}
		<p class="cmp-loading">Loading comparison...</p>
	{:else if compareResult}
		<div class="cmp-grid" style="grid-template-columns: 200px repeat({compareResult.managers.length}, 1fr);">
			<!-- Header row -->
			<div class="cmp-cell cmp-cell--header"></div>
			{#each compareResult.managers as m}
				<div class="cmp-cell cmp-cell--header cmp-cell--name">{m.firm_name}</div>
			{/each}

			<!-- CRD -->
			<div class="cmp-cell cmp-cell--label">CRD</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.crd_number}</div>
			{/each}

			<!-- AUM -->
			<div class="cmp-cell cmp-cell--label">AUM</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.aum_total != null ? formatAUM(m.aum_total) : "\u2014"}</div>
			{/each}

			<!-- AUM Discretionary -->
			<div class="cmp-cell cmp-cell--label">AUM (Disc.)</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.aum_discretionary != null ? formatAUM(m.aum_discretionary) : "\u2014"}</div>
			{/each}

			<!-- State -->
			<div class="cmp-cell cmp-cell--label">State</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.state ?? "\u2014"}</div>
			{/each}

			<!-- Status -->
			<div class="cmp-cell cmp-cell--label">Status</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.registration_status ?? "\u2014"}</div>
			{/each}

			<!-- Accounts -->
			<div class="cmp-cell cmp-cell--label">Accounts</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.total_accounts?.toLocaleString() ?? "\u2014"}</div>
			{/each}

			<!-- Disclosures -->
			<div class="cmp-cell cmp-cell--label">Disclosures</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.compliance_disclosures ?? "\u2014"}</div>
			{/each}

			<!-- Funds -->
			<div class="cmp-cell cmp-cell--label">Funds</div>
			{#each compareResult.managers as m}
				<div class="cmp-cell">{m.funds.length}</div>
			{/each}

			<!-- Jaccard -->
			{#if compareResult.jaccard_overlap != null}
				<div class="cmp-cell cmp-cell--label">Holdings Overlap</div>
				{#each compareResult.managers as _}
					<div class="cmp-cell">{(compareResult.jaccard_overlap * 100).toFixed(1)}%</div>
				{/each}
			{/if}

			<!-- Top sectors -->
			{#if Object.keys(compareResult.sector_allocations).length > 0}
				<div class="cmp-cell cmp-cell--label cmp-cell--section">Sector Allocation</div>
				{#each compareResult.managers as _}
					<div class="cmp-cell cmp-cell--section"></div>
				{/each}
				{#each Object.keys(Object.values(compareResult.sector_allocations)[0] ?? {}).slice(0, 5) as sector}
					<div class="cmp-cell cmp-cell--label">{sector}</div>
					{#each compareResult.managers as m}
						{@const alloc = compareResult.sector_allocations[m.crd_number]}
						<div class="cmp-cell">{alloc?.[sector] != null ? `${(alloc[sector] * 100).toFixed(1)}%` : "\u2014"}</div>
					{/each}
				{/each}
			{/if}
		</div>
	{:else}
		<p class="cmp-loading">No comparison data available.</p>
	{/if}
</ContextPanel>

<style>
	/* ── Page layout ── */
	.mgrs-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 48px);
		overflow: hidden;
	}

	/* ── Top bar ── */
	.mgrs-topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 24px 0;
		flex-shrink: 0;
	}

	.mgrs-topbar-left {
		display: flex;
		align-items: baseline;
		gap: 16px;
	}

	.mgrs-topbar-right {
		display: flex;
		gap: 8px;
	}

	.mgrs-back {
		font-size: 13px;
		color: var(--ii-text-muted);
		text-decoration: none;
	}
	.mgrs-back:hover { color: var(--ii-text-primary); }

	.mgrs-title {
		font-size: 24px;
		font-weight: 800;
		color: var(--ii-text-primary);
		margin: 0;
	}

	/* ── Filter bar ── */
	.mgrs-filterbar {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 24px;
		flex-shrink: 0;
	}

	.mgrs-search {
		width: 280px;
		height: 34px;
		padding: 0 10px 0 34px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: var(--ii-surface-elevated);
		font-size: 13px;
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%2390a1b9' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: 10px center;
	}
	.mgrs-search::placeholder { color: var(--ii-text-muted); }
	.mgrs-search:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 15%, transparent);
	}

	.mgrs-count {
		font-size: 13px;
		color: var(--ii-text-muted);
	}

	/* ── Button ── */
	.mgrs-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 34px;
		padding: 0 16px;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
		border: none;
	}

	.mgrs-btn--primary {
		background: var(--ii-brand-primary, #1447e6);
		color: #fff;
	}
	.mgrs-btn--primary:hover {
		background: var(--ii-brand-primary-hover, #1038c4);
	}

	/* ── Table card ── */
	.mgrs-table-card {
		flex: 1;
		min-height: 0;
		margin: 0 24px 16px;
		background: var(--ii-surface);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-lg);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.mgrs-table-scroll {
		flex: 1;
		overflow-y: auto;
	}

	.mgrs-table {
		width: 100%;
		border-collapse: collapse;
	}

	.mgrs-th {
		position: sticky;
		top: 0;
		padding: 10px 12px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt, #f6f7f9);
		border-bottom: 1px solid var(--ii-border-subtle);
		text-align: left;
		white-space: nowrap;
		z-index: 1;
	}
	.mgrs-th--right { text-align: right; }
	.mgrs-th--check { width: 40px; }
	.mgrs-th--action { width: 60px; }

	.mgrs-row {
		border-bottom: 1px solid var(--ii-border-subtle);
		transition: background 80ms ease;
	}
	.mgrs-row:hover { background: var(--ii-surface-hover, #f8f9fb); }
	.mgrs-row--selected { background: color-mix(in srgb, var(--ii-brand-primary) 5%, transparent); }

	.mgrs-td {
		padding: 10px 12px;
		font-size: 13px;
		color: var(--ii-text-primary);
		white-space: nowrap;
	}
	.mgrs-td--check { width: 40px; text-align: center; }
	.mgrs-td--check input { accent-color: var(--ii-brand-primary, #1447e6); cursor: pointer; }
	.mgrs-td--right { text-align: right; }
	.mgrs-td--mono { font-family: var(--ii-font-mono, monospace); font-size: 12px; }
	.mgrs-td--name { font-weight: 600; max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
	.mgrs-td--action { text-align: center; }

	.mgrs-name-link {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		font-weight: 600;
		color: var(--ii-brand-primary, #1447e6);
		cursor: pointer;
		text-align: left;
	}
	.mgrs-name-link:hover { text-decoration: underline; }

	.mgrs-view-link {
		font-size: 12px;
		font-weight: 600;
		color: var(--ii-brand-primary, #1447e6);
		text-decoration: none;
	}
	.mgrs-view-link:hover { text-decoration: underline; }

	.mgrs-empty {
		text-align: center;
		padding: 40px 12px;
		color: var(--ii-text-muted);
	}

	/* Badge */
	.mgrs-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.mgrs-badge--approved { background: color-mix(in srgb, var(--ii-success) 12%, transparent); color: var(--ii-success); }
	.mgrs-badge--pending { background: color-mix(in srgb, var(--ii-warning) 12%, transparent); color: var(--ii-warning); }
	.mgrs-badge--none { color: var(--ii-text-muted); }

	/* ── Pagination ── */
	.mgrs-pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 16px;
		padding: 10px 16px;
		border-top: 1px solid var(--ii-border-subtle);
		flex-shrink: 0;
	}

	.mgrs-page-btn {
		height: 30px;
		padding: 0 14px;
		border: 1px solid var(--ii-border);
		border-radius: 6px;
		background: var(--ii-surface-elevated);
		color: var(--ii-text-secondary);
		font-size: 12px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 80ms ease;
	}
	.mgrs-page-btn:hover:not(:disabled) { border-color: var(--ii-border-strong); color: var(--ii-text-primary); }
	.mgrs-page-btn:disabled { opacity: 0.4; cursor: not-allowed; }

	.mgrs-page-info {
		font-size: 12px;
		color: var(--ii-text-muted);
	}

	/* ── Compare panel ── */
	.cmp-loading {
		padding: 24px;
		color: var(--ii-text-muted);
		font-size: 13px;
	}

	.cmp-grid {
		display: grid;
		gap: 0;
		padding: 16px;
	}

	.cmp-cell {
		padding: 8px 12px;
		font-size: 13px;
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.cmp-cell--header {
		font-weight: 700;
		font-size: 14px;
		padding-bottom: 12px;
		border-bottom: 2px solid var(--ii-border);
	}

	.cmp-cell--name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cmp-cell--label {
		font-weight: 600;
		color: var(--ii-text-muted);
		font-size: 12px;
	}

	.cmp-cell--section {
		padding-top: 16px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 11px;
		border-bottom: none;
	}
</style>

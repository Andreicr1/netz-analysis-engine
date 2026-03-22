<script lang="ts">
	import {
		PageHeader,
		PageTabs,
		EmptyState,
		Button,
		Input,
		StatusBadge,
		formatNumber,
	} from "@netz/ui";
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import EsmaManagerDrawer from "./EsmaManagerDrawer.svelte";
	import type { PageData } from "./$types";

	/* ── Types ── */

	interface EsmaManagerItem {
		esma_id: string;
		company_name: string;
		country: string | null;
		authorization_status: string | null;
		sec_crd_number: string | null;
		fund_count: number;
	}

	interface EsmaManagerPage {
		items: EsmaManagerItem[];
		total: number;
		page: number;
		page_size: number;
	}

	interface EsmaFundItem {
		isin: string;
		fund_name: string;
		domicile: string | null;
		fund_type: string | null;
		yahoo_ticker: string | null;
		esma_manager_id: string | null;
	}

	interface EsmaFundPage {
		items: EsmaFundItem[];
		total: number;
		page: number;
		page_size: number;
	}

	/* ── Props & context ── */

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	/* ── Derived data ── */

	const defaultManagerPage: EsmaManagerPage = { items: [], total: 0, page: 1, page_size: 25 };
	const defaultFundPage: EsmaFundPage = { items: [], total: 0, page: 1, page_size: 25 };

	let managers = $derived((data.managers ?? defaultManagerPage) as EsmaManagerPage);
	let funds = $derived((data.funds ?? defaultFundPage) as EsmaFundPage);
	let activeTab = $derived((data.activeTab ?? "managers") as string);

	/* ── Filter state ── */

	let searchValue = $state("");
	let countryFilter = $state("");
	let domicileFilter = $state("");
	let fundTypeFilter = $state("");

	/* Sync filter state from URL params on data change */
	$effect(() => {
		const p = data.currentParams ?? {};
		searchValue = p.search ?? "";
		countryFilter = p.country ?? "";
		domicileFilter = p.domicile ?? "";
		fundTypeFilter = p.type ?? "";
	});

	/* ── Search with sequence counter ── */

	let searchSeq = $state(0);

	function onSearchInput() {
		const seq = ++searchSeq;
		setTimeout(() => {
			if (seq !== searchSeq) return;
			applyFilters();
		}, 300);
	}

	/* ── Filter application ── */

	function applyFilters() {
		const params = new URLSearchParams();
		params.set("tab", activeTab);
		if (searchValue) params.set("search", searchValue);
		if (activeTab === "managers" && countryFilter) params.set("country", countryFilter);
		if (activeTab === "funds" && domicileFilter) params.set("domicile", domicileFilter);
		if (activeTab === "funds" && fundTypeFilter) params.set("type", fundTypeFilter);
		params.set("page", "1");
		params.set("page_size", "25");
		goto(`/esma?${params.toString()}`, { invalidateAll: true });
	}

	function clearFilters() {
		searchValue = "";
		countryFilter = "";
		domicileFilter = "";
		fundTypeFilter = "";
		goto(`/esma?tab=${activeTab}`, { invalidateAll: true });
	}

	/* ── Tab switching ── */

	function onTabChange(tab: string) {
		searchValue = "";
		countryFilter = "";
		domicileFilter = "";
		fundTypeFilter = "";
		goto(`/esma?tab=${tab}`, { invalidateAll: true });
	}

	/* ── Pagination ── */

	function goToPage(newPage: number) {
		const url = new URL(window.location.href);
		url.searchParams.set("page", String(newPage));
		goto(url.toString(), { invalidateAll: true });
	}

	let currentPage = $derived(activeTab === "managers" ? managers.page : funds.page);
	let totalItems = $derived(activeTab === "managers" ? managers.total : funds.total);
	let pageSize = $derived(activeTab === "managers" ? managers.page_size : funds.page_size);
	let totalPages = $derived(Math.ceil(totalItems / pageSize));
	let hasNext = $derived(currentPage < totalPages);
	let hasPrev = $derived(currentPage > 1);

	/* ── Manager detail drawer ── */

	let selectedManagerId = $state<string | null>(null);

	function openManagerDrawer(esmaId: string) {
		selectedManagerId = esmaId;
	}

	function closeDrawer() {
		selectedManagerId = null;
	}

	/* ── Sorting ── */

	let sortKey = $state<string | null>(null);
	let sortDir = $state<"asc" | "desc">("asc");

	function toggleSort(key: string) {
		if (sortKey === key) {
			sortDir = sortDir === "asc" ? "desc" : "asc";
		} else {
			sortKey = key;
			sortDir = "asc";
		}
	}

	function sortIndicator(key: string): string {
		if (sortKey !== key) return "";
		return sortDir === "asc" ? " \u2191" : " \u2193";
	}

	function sortItems<T>(items: T[]): T[] {
		if (!sortKey) return items;
		const key = sortKey;
		const sorted = [...items];
		sorted.sort((a, b) => {
			const aVal = (a as unknown as Record<string, unknown>)[key];
			const bVal = (b as unknown as Record<string, unknown>)[key];
			if (aVal == null && bVal == null) return 0;
			if (aVal == null) return 1;
			if (bVal == null) return -1;
			if (typeof aVal === "number" && typeof bVal === "number") {
				return sortDir === "asc" ? aVal - bVal : bVal - aVal;
			}
			const cmp = String(aVal).localeCompare(String(bVal));
			return sortDir === "asc" ? cmp : -cmp;
		});
		return sorted;
	}

	let sortedManagers = $derived(sortItems(managers.items));
	let sortedFunds = $derived(sortItems(funds.items));

	/* ── Tabs config ── */

	const tabs = [
		{ value: "managers", label: "Managers" },
		{ value: "funds", label: "Funds" },
	];
</script>

<PageHeader title="ESMA Universe" />

<PageTabs {tabs} active={activeTab} onChange={onTabChange}>
	{#snippet children(tab: string)}
		<div class="flex gap-6">
			<!-- Filter Sidebar -->
			<aside class="w-64 shrink-0 space-y-4">
				<div>
					<label class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Search</label>
					<Input
						type="text"
						placeholder={tab === "managers" ? "Company name..." : "Fund name or ISIN..."}
						bind:value={searchValue}
						oninput={onSearchInput}
					/>
				</div>

				{#if tab === "managers"}
					<div>
						<label class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Country</label>
						<Input
							type="text"
							placeholder="e.g. DE, FR, IE..."
							bind:value={countryFilter}
							oninput={applyFilters}
						/>
					</div>
				{:else}
					<div>
						<label class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Domicile</label>
						<Input
							type="text"
							placeholder="e.g. Luxembourg, Ireland..."
							bind:value={domicileFilter}
							oninput={applyFilters}
						/>
					</div>
					<div>
						<label class="block text-xs font-medium text-(--netz-text-secondary) mb-1">Fund Type</label>
						<Input
							type="text"
							placeholder="e.g. UCITS, AIF..."
							bind:value={fundTypeFilter}
							oninput={applyFilters}
						/>
					</div>
				{/if}

				<Button variant="outline" size="sm" onclick={clearFilters} class="w-full">
					Clear Filters
				</Button>
			</aside>

			<!-- Main Content -->
			<div class="flex-1 min-w-0">
				{#if tab === "managers"}
					<!-- Managers Table -->
					{#if managers.items.length === 0}
						<EmptyState
							title="No managers found"
							description="Try adjusting your search or filter criteria."
						/>
					{:else}
						<div class="text-xs text-(--netz-text-muted) mb-2">
							{formatNumber(managers.total, 0)} managers
						</div>
						<div class="overflow-x-auto rounded-lg border border-(--netz-border-subtle)">
							<table class="w-full text-sm">
								<thead>
									<tr class="border-b border-(--netz-border-subtle) bg-(--netz-surface-alt)">
										<th
											class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary) cursor-pointer select-none"
											onclick={() => toggleSort("company_name")}
										>
											Company Name{sortIndicator("company_name")}
										</th>
										<th
											class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary) cursor-pointer select-none"
											onclick={() => toggleSort("country")}
										>
											Country{sortIndicator("country")}
										</th>
										<th
											class="px-3 py-2 text-right text-xs font-medium text-(--netz-text-secondary) cursor-pointer select-none"
											onclick={() => toggleSort("fund_count")}
										>
											Funds{sortIndicator("fund_count")}
										</th>
										<th class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary)">
											SEC Cross-Ref
										</th>
									</tr>
								</thead>
								<tbody>
									{#each sortedManagers as mgr (mgr.esma_id)}
										<tr
											class="border-b border-(--netz-border-subtle) hover:bg-(--netz-surface-alt) cursor-pointer transition-colors"
											onclick={() => openManagerDrawer(mgr.esma_id)}
										>
											<td class="px-3 py-2.5 font-medium text-(--netz-text-primary)">
												{mgr.company_name}
											</td>
											<td class="px-3 py-2.5 text-(--netz-text-secondary)">
												{mgr.country ?? "—"}
											</td>
											<td class="px-3 py-2.5 text-right tabular-nums text-(--netz-text-secondary)">
												{formatNumber(mgr.fund_count, 0)}
											</td>
											<td class="px-3 py-2.5">
												{#if mgr.sec_crd_number}
													<StatusBadge status="ok" label="CRD {mgr.sec_crd_number}" />
												{:else}
													<StatusBadge status="neutral" label="No Match" />
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				{:else}
					<!-- Funds Table -->
					{#if funds.items.length === 0}
						<EmptyState
							title="No funds found"
							description="Try adjusting your search or filter criteria."
						/>
					{:else}
						<div class="text-xs text-(--netz-text-muted) mb-2">
							{formatNumber(funds.total, 0)} funds
						</div>
						<div class="overflow-x-auto rounded-lg border border-(--netz-border-subtle)">
							<table class="w-full text-sm">
								<thead>
									<tr class="border-b border-(--netz-border-subtle) bg-(--netz-surface-alt)">
										<th
											class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary) cursor-pointer select-none"
											onclick={() => toggleSort("fund_name")}
										>
											Fund Name{sortIndicator("fund_name")}
										</th>
										<th class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary)">
											ISIN
										</th>
										<th
											class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary) cursor-pointer select-none"
											onclick={() => toggleSort("domicile")}
										>
											Domicile{sortIndicator("domicile")}
										</th>
										<th
											class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary) cursor-pointer select-none"
											onclick={() => toggleSort("fund_type")}
										>
											Type{sortIndicator("fund_type")}
										</th>
										<th class="px-3 py-2 text-left text-xs font-medium text-(--netz-text-secondary)">
											Ticker
										</th>
									</tr>
								</thead>
								<tbody>
									{#each sortedFunds as fund (fund.isin)}
										<tr class="border-b border-(--netz-border-subtle) hover:bg-(--netz-surface-alt) transition-colors">
											<td class="px-3 py-2.5 font-medium text-(--netz-text-primary)">
												{fund.fund_name}
											</td>
											<td class="px-3 py-2.5 font-mono text-xs text-(--netz-text-secondary)">
												{fund.isin}
											</td>
											<td class="px-3 py-2.5 text-(--netz-text-secondary)">
												{fund.domicile ?? "—"}
											</td>
											<td class="px-3 py-2.5 text-(--netz-text-secondary)">
												{fund.fund_type ?? "—"}
											</td>
											<td class="px-3 py-2.5 font-mono text-xs text-(--netz-text-secondary)">
												{#if fund.yahoo_ticker}
													{fund.yahoo_ticker}
												{:else}
													<span class="text-(--netz-text-muted)">—</span>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				{/if}

				<!-- Pagination -->
				{#if totalItems > pageSize}
					<div class="flex items-center justify-between mt-4">
						<span class="text-xs text-(--netz-text-muted)">
							Page {currentPage} of {totalPages}
						</span>
						<div class="flex items-center gap-2">
							<Button variant="outline" size="sm" onclick={() => goToPage(currentPage - 1)} disabled={!hasPrev}>
								Previous
							</Button>
							<Button variant="outline" size="sm" onclick={() => goToPage(currentPage + 1)} disabled={!hasNext}>
								Next
							</Button>
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/snippet}
</PageTabs>

<!-- Manager Detail Drawer -->
<EsmaManagerDrawer esmaId={selectedManagerId} onClose={closeDrawer} {getToken} />

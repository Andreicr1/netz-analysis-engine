<!--
  Unified Screener — Manager-first 3-level drill-down.
  Level 1: Fund Managers (DataTable, server-paginated)
  Level 2: Funds by Manager (Sheet drill-down)
  Level 3: Share Classes by Fund (nested Sheet)
-->
<script lang="ts">
	import { untrack, getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { page as pageStore } from "$app/stores";
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import * as Select from "@investintell/ui/components/ui/select";
	import { DataTable, formatAUM, formatCompact } from "@investintell/ui";
	import { renderComponent } from "@tanstack/svelte-table";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ColumnDef } from "@tanstack/svelte-table";

	// Types
	import type { ManagerRow, ScreenerPage } from "$lib/types/manager-screener";
	import { EMPTY_SCREENER } from "$lib/types/manager-screener";
	import type { UnifiedFundItem } from "$lib/types/catalog";
	import type { ScreeningRun, ScreeningResult } from "$lib/types/screening";

	// Components
	import { ManagerFundsSheet, FundClassesSheet, ScreeningRunPanel } from "$lib/components/screener";
	import RiskDot from "$lib/components/screener/RiskDot.svelte";
	import StrategyBadges from "$lib/components/screener/StrategyBadges.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let { data }: { data: PageData } = $props();

	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};

	// ── Tab state ──
	let activeTab = $state<"catalog" | "screening">(
		(untrack(() => data.tab) as string) === "screening" ? "screening" : "catalog",
	);

	function switchTab(tab: "catalog" | "screening") {
		activeTab = tab;
		if (tab === "catalog") {
			goto("/screener", { invalidateAll: true });
		} else {
			goto("?tab=screening", { invalidateAll: true });
		}
	}

	// ── Managers state (Level 1) ──
	let managers = $derived((data.managers ?? EMPTY_SCREENER) as ScreenerPage);

	// ── Screening state ──
	let screeningRuns = $derived(((data as any).screeningRuns ?? []) as ScreeningRun[]);
	let screeningResults = $derived(((data as any).screeningResults ?? []) as ScreeningResult[]);

	// ── Filter state ──
	let searchQ = $state(initParams.q ?? "");
	let aumMin = $state(initParams.aum_min ?? "");
	let currentPage = $derived(managers.page);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	function buildParams(page = 1): URLSearchParams {
		const params = new URLSearchParams();
		params.set("tab", "catalog");
		if (searchQ) params.set("q", searchQ);
		if (aumMin) params.set("aum_min", aumMin);
		params.set("page", String(page));
		params.set("page_size", "25");
		params.set("sort_by", "aum_total");
		params.set("sort_dir", "desc");
		return params;
	}

	function applyFilters(page = 1) {
		const params = buildParams(page);
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
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

	function goPage(p: number) {
		applyFilters(p);
	}

	let hasActiveFilters = $derived(searchQ.length > 0 || aumMin.length > 0);

	function clearAllFilters() {
		searchQ = "";
		aumMin = "";
		applyFilters();
	}

	// ── Level 2: Funds by Manager ──
	let l2Open = $state(false);
	let l2ManagerId = $state("");
	let l2ManagerName = $state("");
	let l2ManagerAum = $state<number | null>(null);

	function openManagerFunds(mgr: ManagerRow) {
		l2ManagerId = mgr.crd_number;
		l2ManagerName = mgr.firm_name;
		l2ManagerAum = mgr.aum_total;
		l2Open = true;
		// Update URL for deep-linking
		const url = new URL(window.location.href);
		url.searchParams.set("manager", mgr.crd_number);
		history.pushState(null, "", url.toString());
	}

	function closeLevel2() {
		l2Open = false;
		l3Open = false;
		// Remove manager param from URL
		const url = new URL(window.location.href);
		url.searchParams.delete("manager");
		url.searchParams.delete("fund");
		history.pushState(null, "", url.toString());
	}

	// ── Level 3: Share Classes ──
	let l3Open = $state(false);
	let l3FundId = $state("");
	let l3FundName = $state("");

	function openFundClasses(fund: UnifiedFundItem) {
		// Only registered_us funds have share classes
		if (fund.universe !== "registered_us" && fund.universe !== "ucits_eu") {
			// For private funds, navigate to fund detail
			goto(`/screener/fund/${fund.external_id}`);
			return;
		}
		l3FundId = fund.external_id;
		l3FundName = fund.name || "Unnamed Fund";
		l3Open = true;
		// Update URL
		const url = new URL(window.location.href);
		url.searchParams.set("fund", fund.external_id);
		history.pushState(null, "", url.toString());
	}

	function closeLevel3() {
		l3Open = false;
		// Remove fund param from URL
		const url = new URL(window.location.href);
		url.searchParams.delete("fund");
		history.pushState(null, "", url.toString());
	}

	// ── Handle browser back button ──
	function handlePopState() {
		const url = new URL(window.location.href);
		const hasFund = url.searchParams.has("fund");
		const hasManager = url.searchParams.has("manager");

		if (!hasFund && l3Open) {
			l3Open = false;
		}
		if (!hasManager && l2Open) {
			l2Open = false;
			l3Open = false;
		}
	}

	// ── Escape key handler ──
	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			if (l3Open) {
				e.preventDefault();
				closeLevel3();
			} else if (l2Open) {
				e.preventDefault();
				closeLevel2();
			}
		}
	}

	// ── Restore deep-link state from URL on mount ──
	$effect(() => {
		const url = untrack(() => $pageStore.url);
		const mgrParam = url.searchParams.get("manager");
		const fundParam = url.searchParams.get("fund");

		if (mgrParam && !l2Open) {
			l2ManagerId = mgrParam;
			l2ManagerName = ""; // Will be populated by the data
			l2Open = true;

			// Try to find manager name from loaded data
			const mgr = managers.managers.find((m) => m.crd_number === mgrParam);
			if (mgr) {
				l2ManagerName = mgr.firm_name;
				l2ManagerAum = mgr.aum_total;
			}

			if (fundParam) {
				l3FundId = fundParam;
				l3FundName = "";
				l3Open = true;
			}
		}
	});

	// ── Name cleansing ──
	const LEGAL_SUFFIXES_RE =
		/,?\s*\b(LLC|L\.?L\.?C\.?|INC\.?|L\.?P\.?|COMPANY|CORPORATION|CORP\.?|LTD\.?|S\.?A\.?|N\.?A\.?|CO\.?|GROUP|HOLDINGS?|PARTNERS|ADVISORS?|MANAGEMENT|INVESTMENTS?)\b\.?/gi;

	function formatManagerName(name: string): string {
		if (name !== name.toUpperCase()) return name;
		const cleaned = name.replace(LEGAL_SUFFIXES_RE, "").trim().replace(/,\s*$/, "");
		return cleaned
			.toLowerCase()
			.replace(/\b\w/g, (c) => c.toUpperCase())
			.replace(/\bLlc\b/g, "LLC")
			.replace(/\b(Jp|Jpmorgan)\b/g, "JPMorgan")
			.replace(/\bSsga\b/g, "SSGA")
			.replace(/\bPgim\b/g, "PGIM")
			.replace(/\bBbva\b/g, "BBVA");
	}

	// ── Manager DataTable columns ──
	const managerColumns: ColumnDef<ManagerRow, unknown>[] = [
		{
			accessorKey: "firm_name",
			header: "Manager",
			cell: ({ row }) => formatManagerName(row.original.firm_name),
			enableSorting: true,
		},
		{
			accessorKey: "crd_number",
			header: "CRD",
			cell: ({ row }) => row.original.crd_number,
			enableSorting: false,
			meta: { muted: true },
		},
		{
			id: "risk",
			header: "",
			cell: ({ row }) =>
				renderComponent(RiskDot, { count: row.original.compliance_disclosures ?? 0 }),
			enableSorting: false,
			meta: { centered: true },
		},
		{
			id: "strategy",
			header: "Funds",
			cell: ({ row }) =>
				renderComponent(StrategyBadges, {
					hedge_fund_count: row.original.hedge_fund_count,
					pe_fund_count: row.original.pe_fund_count,
					vc_fund_count: row.original.vc_fund_count,
				}),
			enableSorting: false,
		},
		{
			accessorKey: "aum_total",
			header: "AUM",
			cell: ({ row }) =>
				row.original.aum_total != null ? formatAUM(row.original.aum_total) : "\u2014",
			enableSorting: true,
			meta: { numeric: true },
		},
	];

	// ── CSV Export ──
	function exportCSV() {
		const items = managers.managers;
		if (items.length === 0) return;
		const headers = ["Manager", "CRD", "AUM", "13F Portfolio", "HF", "PE", "VC", "Disclosures"];
		const lines = [
			headers.join(","),
			...items.map((r) =>
				[
					`"${formatManagerName(r.firm_name)}"`,
					r.crd_number,
					r.aum_total ?? "",
					r.portfolio_value ?? "",
					r.hedge_fund_count ?? "",
					r.pe_fund_count ?? "",
					r.vc_fund_count ?? "",
					r.compliance_disclosures ?? "",
				].join(","),
			),
		];
		const blob = new Blob([lines.join("\n")], { type: "text/csv" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `screener-managers-${new Date().toISOString().slice(0, 10)}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}
</script>

<svelte:window onpopstate={handlePopState} onkeydown={handleKeydown} />

<div class="scr-page">
	<!-- ════════════════ HEADER BAR ════════════════ -->
	<div class="scr-topbar">
		<div class="scr-topbar-left">
			<h1 class="scr-title">Screener</h1>
		</div>
		<div class="scr-topbar-right">
			{#if activeTab === "catalog"}
				<button class="scr-btn scr-btn--outline" onclick={exportCSV}>
					<svg
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline
							points="7 10 12 15 17 10"
						/><line x1="12" y1="15" x2="12" y2="3" /></svg
					>
					Export
				</button>
			{/if}
		</div>
	</div>

	<!-- ════════════════ TABS ════════════════ -->
	<Tabs.Root bind:value={activeTab} onValueChange={(v) => switchTab(v as "catalog" | "screening")}>
		<Tabs.List class="scr-tabs">
			<Tabs.Trigger value="catalog">Catalog</Tabs.Trigger>
			<Tabs.Trigger value="screening">Screening</Tabs.Trigger>
		</Tabs.List>
	</Tabs.Root>

	{#if activeTab === "catalog"}
		<!-- ════════════════ FILTER BAR ════════════════ -->
		<div class="scr-filterbar">
			<input
				class="scr-search"
				type="text"
				placeholder="Search managers by name or CRD..."
				bind:value={searchQ}
				oninput={debouncedSearch}
				onkeydown={handleSearchKeydown}
			/>

			<Select.Root
				type="single"
				value={aumMin}
				onValueChange={(v) => {
					aumMin = v;
					applyFilters();
				}}
			>
				<Select.Trigger class="h-[34px] w-auto min-w-[140px] text-[13px]">
					{aumMin === "100000000"
						? "AUM $100M+"
						: aumMin === "500000000"
							? "AUM $500M+"
							: aumMin === "1000000000"
								? "AUM $1B+"
								: aumMin === "5000000000"
									? "AUM $5B+"
									: aumMin === "10000000000"
										? "AUM $10B+"
										: aumMin === "50000000000"
											? "AUM $50B+"
											: "AUM: Any"}
				</Select.Trigger>
				<Select.Content>
					<Select.Item value="">AUM: Any</Select.Item>
					<Select.Item value="100000000">AUM $100M+</Select.Item>
					<Select.Item value="500000000">AUM $500M+</Select.Item>
					<Select.Item value="1000000000">AUM $1B+</Select.Item>
					<Select.Item value="5000000000">AUM $5B+</Select.Item>
					<Select.Item value="10000000000">AUM $10B+</Select.Item>
					<Select.Item value="50000000000">AUM $50B+</Select.Item>
				</Select.Content>
			</Select.Root>

			<span class="scr-count"
				>{managers.total_count.toLocaleString()} manager{managers.total_count !== 1
					? "s"
					: ""}</span
			>

			{#if hasActiveFilters}
				<button class="scr-clear-btn" onclick={clearAllFilters}>Clear</button>
			{/if}
		</div>

		<!-- ════════════════ MANAGER TABLE (Level 1) ════════════════ -->
		<div class="scr-table-card">
			<DataTable
				data={managers.managers}
				columns={managerColumns}
				pageSize={managers.page_size}
				totalCount={managers.total_count}
				onRowClick={(row) => openManagerFunds(row as ManagerRow)}
			/>

		</div>
	{:else}
		<!-- ════════════════ SCREENING TAB ════════════════ -->
		<ScreeningRunPanel runs={screeningRuns} results={screeningResults} />
	{/if}
</div>

<!-- ════════════════ Level 2: Funds by Manager ════════════════ -->
<ManagerFundsSheet
	bind:open={l2Open}
	managerId={l2ManagerId}
	managerName={l2ManagerName}
	managerAum={l2ManagerAum}
	onClose={closeLevel2}
	onFundClick={openFundClasses}
/>

<!-- ════════════════ Level 3: Share Classes ════════════════ -->
<FundClassesSheet
	bind:open={l3Open}
	fundId={l3FundId}
	fundName={l3FundName}
	managerName={l2ManagerName}
	onClose={closeLevel3}
/>

<style>
	/* ── Full-height page layout ── */
	.scr-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 48px);
		overflow: hidden;
	}

	/* ── Top bar (title + export) ── */
	.scr-topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 24px 0;
		flex-shrink: 0;
	}

	.scr-topbar-left {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.scr-topbar-right {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.scr-title {
		font-size: 24px;
		font-weight: 800;
		color: var(--ii-text-primary);
		margin: 0;
	}

	/* ── Tabs (shadcn overrides) ── */
	:global(.scr-tabs) {
		padding: 0 24px;
		flex-shrink: 0;
	}

	/* ── Horizontal filter bar ── */
	.scr-filterbar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 24px;
		flex-shrink: 0;
		flex-wrap: wrap;
	}

	.scr-search {
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

	.scr-search::placeholder {
		color: var(--ii-text-muted);
	}
	.scr-search:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 15%, transparent);
	}

	.scr-count {
		font-size: 13px;
		color: var(--ii-text-muted);
		margin-left: auto;
	}

	.scr-clear-btn {
		height: 34px;
		padding: 0 14px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
	}

	.scr-clear-btn:hover {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
	}

	/* ── Table card (fills remaining height) ── */
	.scr-table-card {
		flex: 1;
		min-height: 0;
		margin: 0 24px 16px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.scr-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
		border: none;
	}

	.scr-btn--outline {
		background: transparent;
		border: 1px solid var(--ii-border);
		color: var(--ii-text-secondary);
	}

	.scr-btn--outline:hover {
		background: var(--ii-surface-alt);
		border-color: var(--ii-border-strong);
		color: var(--ii-text-primary);
	}

</style>

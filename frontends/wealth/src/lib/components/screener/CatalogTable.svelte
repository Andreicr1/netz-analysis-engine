<!--
  Catalog table with Manager → Fund → Class hierarchy.
  Sortable headers, neutral AUM formatting, strategy column.
  Server-side pagination synced with URL params.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import "./screener.css";
	import { formatCompact, formatPercent } from "@investintell/ui";
	import type { UnifiedFundItem, UnifiedCatalogPage } from "$lib/types/catalog";
	import { EMPTY_CATALOG_PAGE, FUND_TYPE_LABELS } from "$lib/types/catalog";

	type SortField = "manager" | "name" | "aum" | "strategy";
	type SortDir = "asc" | "desc";

	interface FundGroup {
		fund_key: string;
		representative: UnifiedFundItem;
		classes: UnifiedFundItem[];
		has_classes: boolean;
		has_vintages: boolean;
	}

	interface ManagerGroup {
		manager_key: string;
		manager_name: string;
		manager_id: string | null;
		funds: FundGroup[];
		total_aum: number | null;
		is_standalone: boolean; // funds without manager
	}

	interface Props {
		catalog: UnifiedCatalogPage;
		searchQ: string;
		currentSort: string;
		infiniteScroll?: boolean;
		isLoadingMore?: boolean;
		sentinelEl?: HTMLElement | null;
		onSelectFund: (item: UnifiedFundItem) => void;
		onSendToDDReview: (items: UnifiedFundItem[]) => void;
		onPageChange?: (page: number) => void;
		onSortChange: (sort: string) => void;
		onOpenManager: (managerId: string) => void;
	}

	let {
		catalog = EMPTY_CATALOG_PAGE,
		searchQ = "",
		currentSort = "name_asc",
		infiniteScroll = false,
		isLoadingMore = false,
		sentinelEl = $bindable(null),
		onSelectFund,
		onSendToDDReview,
		onPageChange,
		onSortChange,
		onOpenManager,
	}: Props = $props();

	let totalPages = $derived(Math.ceil(catalog.total / catalog.page_size) || 1);

	// ── Parse current sort into field + direction ──
	let sortField = $derived.by((): SortField => {
		if (currentSort.startsWith("manager")) return "manager";
		if (currentSort.startsWith("aum")) return "aum";
		if (currentSort.startsWith("strategy")) return "strategy";
		return "name";
	});
	let sortDir = $derived<SortDir>(currentSort.endsWith("_desc") ? "desc" : "asc");

	function handleSort(field: SortField) {
		const defaultDir: Record<SortField, SortDir> = {
			manager: "asc",
			name: "asc",
			aum: "desc",
			strategy: "asc",
		};
		let dir: SortDir;
		if (sortField === field) {
			dir = sortDir === "asc" ? "desc" : "asc";
		} else {
			dir = defaultDir[field];
		}
		onSortChange(`${field === "name" ? "name" : field}_${dir}`);
	}

	function sortIndicator(field: SortField): string {
		if (sortField !== field) return "";
		return sortDir === "asc" ? " \u25B2" : " \u25BC";
	}

	// ── Group items: Manager → Fund → Class ──
	let managerGroups = $derived.by((): ManagerGroup[] => {
		// Step 1: group items by fund (external_id)
		const fundMap = new Map<string, UnifiedFundItem[]>();
		for (const item of catalog.items) {
			const key = item.external_id;
			if (!fundMap.has(key)) fundMap.set(key, []);
			fundMap.get(key)!.push(item);
		}

		const fundGroups: FundGroup[] = Array.from(fundMap.entries()).map(([key, items]) => ({
			fund_key: key,
			representative: items[0]!,
			classes: items,
			has_classes:
				items[0]!.universe === "registered_us" &&
				items.length > 1 &&
				items.some((i) => i.class_id != null && i.class_id !== ""),
			has_vintages:
				items[0]!.universe === "private_us" &&
				items.some((i) => i.vintage_year != null) &&
				items[0]!.fund_type !== "Hedge Fund",
		}));

		// Step 2: group funds by manager
		const mgrMap = new Map<string, FundGroup[]>();
		const standaloneGroups: FundGroup[] = [];

		for (const fg of fundGroups) {
			const mgrKey = fg.representative.manager_id ?? fg.representative.manager_name;
			if (mgrKey) {
				if (!mgrMap.has(mgrKey)) mgrMap.set(mgrKey, []);
				mgrMap.get(mgrKey)!.push(fg);
			} else {
				standaloneGroups.push(fg);
			}
		}

		const groups: ManagerGroup[] = [];

		// Manager-grouped funds
		for (const [key, funds] of mgrMap) {
			const rep = funds[0]!.representative;
			let totalAum: number | null = null;
			for (const fg of funds) {
				if (fg.representative.aum != null) {
					totalAum = (totalAum ?? 0) + fg.representative.aum;
				}
			}
			groups.push({
				manager_key: key,
				manager_name: rep.manager_name ?? "Unknown Manager",
				manager_id: rep.manager_id,
				funds,
				total_aum: totalAum,
				is_standalone: false,
			});
		}

		// Sort real managers: by name (asc) or AUM depending on current sort
		groups.sort((a, b) => {
			if (currentSort.startsWith("aum")) {
				const dir = currentSort.endsWith("desc") ? -1 : 1;
				return dir * ((a.total_aum ?? 0) - (b.total_aum ?? 0));
			}
			return a.manager_name.localeCompare(b.manager_name);
		});

		// Standalone funds — ONE group at the end (not one per fund)
		if (standaloneGroups.length > 0) {
			let totalAum: number | null = null;
			for (const fg of standaloneGroups) {
				if (fg.representative.aum != null) {
					totalAum = (totalAum ?? 0) + fg.representative.aum;
				}
			}
			groups.push({
				manager_key: "standalone",
				manager_name: "",
				manager_id: null,
				funds: standaloneGroups,
				total_aum: totalAum,
				is_standalone: true,
			});
		}

		return groups;
	});

	// ── Expand / select state ──
	let expandedManagers = $state<Set<string>>(new Set());
	let expandedFunds = $state<Set<string>>(new Set());
	let selectedClasses = $state<Set<string>>(new Set());

	// Reset expanded state on filter/page change (not on infinite scroll append)
	let prevItemCount = 0;
	$effect(() => {
		const count = catalog.items.length;
		// In infinite scroll, items grow monotonically — reset only when count drops (filter change)
		if (!infiniteScroll || count < prevItemCount) {
			expandedManagers = new Set();
			expandedFunds = new Set();
		}
		prevItemCount = count;
	});

	function toggleManager(key: string) {
		const next = new Set(expandedManagers);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		expandedManagers = next;
	}

	function toggleFund(fundKey: string) {
		const next = new Set(expandedFunds);
		if (next.has(fundKey)) next.delete(fundKey);
		else next.add(fundKey);
		expandedFunds = next;
	}

	function toggleClass(item: UnifiedFundItem) {
		const key = `${item.external_id}:${item.class_id}`;
		const next = new Set(selectedClasses);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		selectedClasses = next;
	}

	function isClassSelected(item: UnifiedFundItem): boolean {
		return selectedClasses.has(`${item.external_id}:${item.class_id}`);
	}

	function handleSendSelected() {
		const items: UnifiedFundItem[] = [];
		for (const key of selectedClasses) {
			const [cik, classId] = key.split(":");
			const item = catalog.items.find((i) => i.external_id === cik && i.class_id === classId);
			if (item) items.push(item);
		}
		onSendToDDReview(items);
		selectedClasses = new Set();
	}

	function fundTypeLabel(ft: string): string {
		return FUND_TYPE_LABELS[ft] ?? ft.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	function formatFundName(name: string | null | undefined): string {
		if (!name || name.trim() === "" || name === "()") return "Unnamed Fund";
		return name;
	}

	function formatAumNeutral(value: number | null | undefined): string {
		if (value == null) return "\u2014";
		return formatCompact(value);
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
	{#if selectedClasses.size > 0}
		<button class="ct-send-dd-btn" onclick={handleSendSelected}>
			Send {selectedClasses.size} class{selectedClasses.size > 1 ? "es" : ""} to DD Review
		</button>
	{/if}
	{#if !infiniteScroll}
		<span class="ct-page-label">
			Page {catalog.page} of {totalPages}
		</span>
	{/if}
</div>

{#if catalog.items.length === 0}
	<div class="scr-empty">No funds found. Adjust filters or search.</div>
{:else}
	<div class="scr-table-wrap">
		<table class="scr-table ct-tree-table">
			<thead>
				<tr>
					<th class="ct-col-expand"></th>
					<th class="ct-col-check"></th>
					<th class="ct-col-type">
						<button class="ct-sort-btn" onclick={() => handleSort("name")}>
							Type{sortIndicator("name")}
						</button>
					</th>
					<th class="ct-col-name">
						<button class="ct-sort-btn" onclick={() => handleSort("manager")}>
							Manager / Fund / Class{sortIndicator("manager")}
						</button>
					</th>
					<th class="ct-col-strategy">
						<button class="ct-sort-btn" onclick={() => handleSort("strategy")}>
							Strategy{sortIndicator("strategy")}
						</button>
					</th>
					<th class="ct-col-aum">
						<button class="ct-sort-btn ct-sort-btn--right" onclick={() => handleSort("aum")}>
							AUM{sortIndicator("aum")}
						</button>
					</th>
					<th class="ct-col-er">ER%</th>
					<th class="ct-col-ret">1Y Ret</th>
					<th class="ct-col-action"></th>
				</tr>
			</thead>
			<tbody>
				{#each managerGroups as mg (mg.manager_key)}
					<!-- Manager row (L1) — Always show for structured tree -->
					<tr
						class="scr-inst-row ct-manager-row"
						class:ct-manager-row--expanded={expandedManagers.has(mg.manager_key)}
						onclick={() => toggleManager(mg.manager_key)}
					>
						<td class="ct-col-expand">
							<span class="ct-chevron" class:ct-chevron--open={expandedManagers.has(mg.manager_key)}>&#9654;</span>
						</td>
						<td class="ct-col-check"></td>
						<td class="ct-type-label">Manager</td>
						<td class="ct-col-name">
							<div class="ct-manager-name-cell">
								<button
									class="ct-manager-link"
									onclick={(e) => {
										e.stopPropagation();
										if (mg.manager_id) onOpenManager(mg.manager_id);
									}}
									title={mg.manager_id ? `View manager (CRD: ${mg.manager_id})` : undefined}
								>
									{mg.manager_name || "Standalone Funds"}
								</button>
								<span class="ct-fund-count">{mg.funds.length} fund{mg.funds.length !== 1 ? "s" : ""}</span>
							</div>
						</td>
						<td></td>
						<td class="std-aum">{formatAumNeutral(mg.total_aum)}</td>
						<td></td>
						<td></td>
						<td></td>
					</tr>

					<!-- Fund rows (L2) — shown when manager expanded -->
					{#if expandedManagers.has(mg.manager_key)}
						{#each mg.funds as group (group.fund_key)}
							<tr
								class="scr-inst-row ct-fund-row"
								class:ct-fund-row--nested={true}
								class:ct-fund-row--expanded={expandedFunds.has(group.fund_key)}
								onclick={() => {
									// Navigate to individual fund page
									goto(`/screener/fund/${group.representative.external_id}`);
								}}
							>
								<td class="ct-col-expand">
									{#if group.has_classes || group.has_vintages}
										<button 
											class="ct-chevron-btn" 
											onclick={(e) => { e.stopPropagation(); toggleFund(group.fund_key); }}
										>
											<span class="ct-chevron ct-chevron--fund" class:ct-chevron--open={expandedFunds.has(group.fund_key)}>&#9654;</span>
										</button>
									{/if}
								</td>
								<td class="ct-col-check"></td>
								<td>
									<span class="ct-type-label">{fundTypeLabel(group.representative.fund_type)}</span>
								</td>
								<td class="ct-col-name">
									<div class="ct-fund-name-cell ct-fund-name-cell--nested">
										<span class="ct-fund-name" class:ct-fund-name--unnamed={!group.representative.name || group.representative.name.trim() === "" || group.representative.name === "()"}>
											{formatFundName(group.representative.name)}
										</span>
										{#if group.representative.ticker}
											<span class="ct-ticker">{group.representative.ticker}</span>
										{/if}
										{#if group.has_classes}
											<span class="ct-class-count">{group.classes.length} classes</span>
										{/if}
										{#if group.representative.is_index}<span class="ct-ncen-badge">Index</span>{/if}
										{#if group.representative.is_target_date}<span class="ct-ncen-badge">Target Date</span>{/if}
										{#if group.representative.is_fund_of_fund}<span class="ct-ncen-badge">FoF</span>{/if}
									</div>
								</td>
								<td>
									<span class="ct-strategy-label">{group.representative.strategy_label ?? "\u2014"}</span>
								</td>
								<td class="std-aum">{formatAumNeutral(group.representative.aum)}</td>
								<td class="ct-col-er">{group.representative.expense_ratio_pct != null ? formatPercent(Number(group.representative.expense_ratio_pct) / 100) : "\u2014"}</td>
								<td class="ct-col-ret">{#if group.representative.fund_type === "money_market" && group.representative.seven_day_gross_yield != null}{formatPercent(Number(group.representative.seven_day_gross_yield) / 100)}{:else if group.representative.avg_annual_return_1y != null}{formatPercent(Number(group.representative.avg_annual_return_1y) / 100)}{:else}{"\u2014"}{/if}</td>
								<td class="ct-col-action">
									<button
										class="ct-dd-btn"
										title="Run DD Report"
										onclick={(e) => { e.stopPropagation(); onSendToDDReview([group.representative]); }}
									>
										DD Review
									</button>
								</td>
							</tr>

							<!-- Class rows (L3) — only if expanded -->
							{#if group.has_classes && expandedFunds.has(group.fund_key)}
								{#each group.classes as cls (`${cls.external_id}:${cls.class_id}`)}
									<tr
										class="scr-inst-row ct-class-row"
										class:ct-class-row--selected={isClassSelected(cls)}
									>
										<td class="ct-col-expand"></td>
										<td class="ct-col-check">
											<input
												type="checkbox"
												class="ct-class-checkbox"
												checked={isClassSelected(cls)}
												onchange={() => toggleClass(cls)}
												onclick={(e) => e.stopPropagation()}
											/>
										</td>
										<td></td>
										<td class="ct-col-name">
											<div class="ct-class-name-cell">
												<span class="ct-class-name">{cls.class_name ?? cls.class_id ?? "\u2014"}</span>
												{#if cls.ticker}
													<span class="ct-ticker">{cls.ticker}</span>
												{/if}
												<button
													class="ct-detail-link"
													onclick={(e) => { e.stopPropagation(); onSelectFund(cls); }}
												>
													View details &rarr;
												</button>
											</div>
										</td>
										<td></td>
										<td class="ct-col-er">{cls.expense_ratio_pct != null ? formatPercent(Number(cls.expense_ratio_pct) / 100) : ""}</td>
										<td class="ct-col-ret">{cls.avg_annual_return_1y != null ? formatPercent(Number(cls.avg_annual_return_1y) / 100) : ""}</td>
										<td></td>
									</tr>
								{/each}
							{/if}

							<!-- Vintage rows (L3) — PE/VC private funds only -->
							{#if group.has_vintages && expandedFunds.has(group.fund_key)}
								{#each group.classes.toSorted((a, b) => (b.vintage_year ?? 0) - (a.vintage_year ?? 0)) as vintage (`${vintage.external_id}:${vintage.vintage_year}`)}
									<tr class="scr-inst-row ct-vintage-row" onclick={(e) => { e.stopPropagation(); onSelectFund(vintage); }}>
										<td class="ct-col-expand"></td>
										<td class="ct-col-check"></td>
										<td></td>
										<td class="ct-col-name">
											<div class="ct-vintage-name-cell">
												<span class="ct-vintage-label">
													{vintage.vintage_year != null ? `Vintage ${vintage.vintage_year}` : vintage.name}
												</span>
												{#if vintage.aum != null}
													<span class="ct-vintage-aum">{formatAumNeutral(vintage.aum)}</span>
												{/if}
												{#if vintage.investor_count != null}
													<span class="ct-vintage-meta">{vintage.investor_count} investors</span>
												{/if}
											</div>
										</td>
										<td>
											<span class="ct-strategy-label">{vintage.strategy_label ?? "\u2014"}</span>
										</td>
										<td class="std-aum">{formatAumNeutral(vintage.aum)}</td>
										<td></td>
										<td></td>
										<td></td>
									</tr>
								{/each}
							{/if}
						{/each}
					{/if}
				{/each}
			</tbody>
		</table>

		{#if infiniteScroll}
			<!-- Sentinel: IntersectionObserver in parent triggers loadMore() -->
			<div bind:this={sentinelEl} class="ct-scroll-sentinel" aria-hidden="true"></div>

			{#if isLoadingMore}
				<div class="ct-loading-more">
					<span class="ct-loading-dot"></span>
					<span class="ct-loading-dot"></span>
					<span class="ct-loading-dot"></span>
				</div>
			{/if}
		{/if}
	</div>

	{#if !infiniteScroll}
	<!-- Server-side pagination -->
	<div class="scr-pagination">
		<button class="scr-page-btn" disabled={catalog.page <= 1} onclick={() => onPageChange?.(catalog.page - 1)}>
			Prev
		</button>
		<span class="scr-page-info">
			{catalog.page} / {totalPages}
		</span>
		<button class="scr-page-btn" disabled={!catalog.has_next} onclick={() => onPageChange?.(catalog.page + 1)}>
			Next
		</button>
	</div>
	{/if}
{/if}

<style>
	.ct-scroll-sentinel {
		height: 1px;
		width: 100%;
	}

	.ct-loading-more {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 6px;
		padding: 20px;
	}

	.ct-loading-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--ii-text-muted, #9ca3af);
		animation: ct-dot-pulse 1.2s ease-in-out infinite;
	}

	.ct-loading-dot:nth-child(2) { animation-delay: 0.2s; }
	.ct-loading-dot:nth-child(3) { animation-delay: 0.4s; }

	@keyframes ct-dot-pulse {
		0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
		40% { opacity: 1; transform: scale(1); }
	}

	.ct-page-label {
		margin-left: auto;
		font-size: 12px;
		color: #90a1b9;
		font-variant-numeric: tabular-nums;
	}

	/* ── Sort buttons ── */
	.ct-sort-btn {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		color: inherit;
		cursor: pointer;
		white-space: nowrap;
		user-select: none;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 1.1px;
	}
	.ct-sort-btn:hover { color: #1d293d; }
	.ct-sort-btn--right { text-align: right; display: block; width: 100%; }

	/* ── Column widths ── */
	.ct-col-expand { width: 28px; }
	.ct-col-check  { width: 36px; text-align: center; }
	.ct-col-type   { width: 110px; }
	.ct-col-name   { min-width: 280px; }
	.ct-col-strategy { width: 150px; }
	.ct-col-aum    { width: 90px; text-align: right; }
	.ct-col-action { width: 90px; text-align: right; }
	.ct-col-er     { width: 60px; text-align: right; font-variant-numeric: tabular-nums; font-size: var(--ii-text-small, 0.8125rem); color: var(--ii-text-secondary); }
	.ct-col-ret    { width: 70px; text-align: right; font-variant-numeric: tabular-nums; font-size: var(--ii-text-small, 0.8125rem); color: var(--ii-text-secondary); }
	.ct-ncen-badge { display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 10px; font-weight: 600; background: color-mix(in srgb, var(--ii-info) 12%, transparent); color: var(--ii-info); white-space: nowrap; }

	/* ── Manager row (L1) ── */
	.ct-manager-row {
		cursor: pointer;
		background: #f8fafc;
		border-bottom: 1px solid #e2e8f0;
	}
	.ct-manager-row:hover { background: #f1f5f9; }
	.ct-manager-row--expanded { background: #f1f5f9; }

	.ct-manager-name-cell {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.ct-manager-link {
		background: none;
		border: none;
		padding: 0;
		font-size: 14px;
		font-weight: 700;
		color: #1d293d;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		text-align: left;
	}
	.ct-manager-link:hover { color: #155dfc; text-decoration: underline; }

	.ct-fund-count {
		font-size: 11px;
		color: #6b7280;
		background: #e5e7eb;
		border-radius: 8px;
		padding: 1px 7px;
		font-weight: 600;
	}

	/* ── Fund row (L2) ── */
	.ct-fund-row { cursor: pointer; }
	.ct-fund-row:hover { background: #f8fafc; }
	.ct-fund-row--nested { border-left: 2px solid #e2e8f0; }
	.ct-fund-row--expanded { background: #f8fafc; }

	.ct-fund-name-cell {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.ct-fund-name-cell--nested {
		padding-left: 16px;
	}

	.ct-fund-name {
		font-weight: 600;
		font-size: 14px;
		color: #1d293d;
		max-width: 300px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ct-fund-name--unnamed {
		color: #9ca3af;
		font-style: italic;
	}

	.ct-ticker {
		font-size: 11px;
		font-weight: 700;
		color: #62748e;
		background: #f1f5f9;
		border-radius: 4px;
		padding: 1px 6px;
		font-family: Consolas, var(--ii-font-mono, monospace);
		letter-spacing: 0.3px;
		flex-shrink: 0;
	}

	.ct-class-count {
		font-size: 11px;
		color: #6b7280;
		background: #f3f4f6;
		border-radius: 8px;
		padding: 1px 7px;
		flex-shrink: 0;
	}

	.ct-type-label {
		font-size: 12px;
		color: #62748e;
		font-weight: 500;
		white-space: nowrap;
	}

	.ct-strategy-label {
		font-size: 13px;
		color: #374151;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 150px;
		display: block;
	}

	.ct-dd-btn {
		padding: 3px 10px;
		font-size: 11px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		color: var(--ii-brand-primary, #1447e6);
		background: color-mix(in srgb, var(--ii-brand-primary, #1447e6) 8%, transparent);
		border: 1px solid color-mix(in srgb, var(--ii-brand-primary, #1447e6) 20%, transparent);
		border-radius: 6px;
		cursor: pointer;
		white-space: nowrap;
		transition: all 120ms ease;
	}
	.ct-dd-btn:hover {
		background: color-mix(in srgb, var(--ii-brand-primary, #1447e6) 15%, transparent);
		border-color: var(--ii-brand-primary, #1447e6);
	}

	/* ── Chevron ── */
	.ct-chevron {
		display: inline-block;
		font-size: 10px;
		color: #62748e;
		transition: transform 120ms ease;
		user-select: none;
	}
	.ct-chevron--open { transform: rotate(90deg); }
	.ct-chevron--fund { font-size: 9px; color: #9ca3af; }

	.ct-chevron-btn {
		background: none;
		border: none;
		padding: 4px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 4px;
	}
	.ct-chevron-btn:hover { background: #e2e8f0; }

	/* ── Vintage rows (L3 — PE/VC) ── */
	.ct-vintage-row {
		background: var(--ii-surface-alt, #fbfdff);
		cursor: pointer;
	}
	.ct-vintage-row:hover {
		background: var(--ii-bg-hover, #f0f7ff);
	}

	.ct-vintage-name-cell {
		display: flex;
		align-items: center;
		gap: 10px;
		padding-left: 36px;
	}

	.ct-vintage-label {
		font-size: 13px;
		font-weight: 600;
		color: var(--ii-text-primary, #1d293d);
		font-variant-numeric: tabular-nums;
	}

	.ct-vintage-aum {
		font-size: 12px;
		color: var(--ii-text-secondary, #62748e);
		font-variant-numeric: tabular-nums;
	}

	.ct-vintage-meta {
		font-size: 11px;
		color: var(--ii-text-muted, #9ca3af);
	}

	/* ── Class rows (L3) ── */
	.ct-class-row { background: #fbfdff; }
	.ct-class-row:hover { background: #f0f7ff; }
	.ct-class-row--selected { background: #eff6ff !important; }

	.ct-class-name-cell {
		display: flex;
		align-items: center;
		gap: 8px;
		padding-left: 36px;
	}

	.ct-class-name {
		font-size: 13px;
		font-weight: 500;
		color: #374151;
	}

	.ct-class-checkbox {
		cursor: pointer;
		width: 15px;
		height: 15px;
		accent-color: #1447e6;
	}

	/* ── Send to DD / Detail ── */
	.ct-send-dd-btn {
		margin-left: auto;
		padding: 6px 14px;
		background: #1447e6;
		color: #fff;
		border: none;
		border-radius: 6px;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
	}
	.ct-send-dd-btn:hover { background: #0f3ccc; }

	.ct-detail-link {
		background: none;
		border: none;
		padding: 0;
		font-size: 12px;
		color: #1447e6;
		cursor: pointer;
		text-decoration: underline;
		font-family: var(--ii-font-sans);
		margin-left: auto;
	}
	.ct-detail-link:hover { color: #0f3ccc; }

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

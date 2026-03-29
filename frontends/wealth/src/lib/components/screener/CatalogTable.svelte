<!--
  Server-side paginated catalog table for UnifiedFundItem[].
  Groups rows by fund (external_id) and expands share classes for registered_us funds.
  No infinite scroll — clean Prev/Next pagination synced with URL params.
-->
<script lang="ts">
	import "./screener.css";
	import { formatAUM } from "@investintell/ui";
	import type { UnifiedFundItem, UnifiedCatalogPage } from "$lib/types/catalog";
	import { EMPTY_CATALOG_PAGE, UNIVERSE_LABELS } from "$lib/types/catalog";

	interface FundGroup {
		fund_key: string;
		representative: UnifiedFundItem;
		classes: UnifiedFundItem[];
		has_classes: boolean;
	}

	interface Props {
		catalog: UnifiedCatalogPage;
		searchQ: string;
		onSelectFund: (item: UnifiedFundItem) => void;
		onSendToDDReview: (items: UnifiedFundItem[]) => void;
		onPageChange: (page: number) => void;
	}

	let {
		catalog = EMPTY_CATALOG_PAGE,
		searchQ = "",
		onSelectFund,
		onSendToDDReview,
		onPageChange,
	}: Props = $props();

	let totalPages = $derived(Math.ceil(catalog.total / catalog.page_size) || 1);

	// ── Group items by fund (external_id) ──
	let fundGroups = $derived.by((): FundGroup[] => {
		const map = new Map<string, UnifiedFundItem[]>();
		for (const item of catalog.items) {
			const key = item.external_id;
			if (!map.has(key)) map.set(key, []);
			map.get(key)!.push(item);
		}
		return Array.from(map.entries()).map(([key, items]) => ({
			fund_key: key,
			representative: items[0]!,
			classes: items,
			has_classes: items[0]!.universe === "registered_us" && items.length > 1 && items.some((i) => i.class_id != null),
		}));
	});

	// ── Expand / select state ──
	let expandedFunds = $state<Set<string>>(new Set());
	let selectedClasses = $state<Set<string>>(new Set());

	function toggleExpand(fundKey: string) {
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
	{#if selectedClasses.size > 0}
		<button class="ct-send-dd-btn" onclick={handleSendSelected}>
			Send {selectedClasses.size} class{selectedClasses.size > 1 ? "es" : ""} to DD Review
		</button>
	{/if}
	<span class="ct-page-label">
		Page {catalog.page} of {totalPages}
	</span>
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
					<th class="sth-univ">Universe</th>
					<th>Ticker</th>
					<th class="sth-name">Name / Class</th>
					<th>Manager</th>
					<th>Type</th>
					<th class="sth-aum">AUM</th>
					<th>Region</th>
					<th>Disclosure</th>
				</tr>
			</thead>
			<tbody>
				{#each fundGroups as group (group.fund_key)}
					<!-- Fund row (parent) -->
					<tr
						class="scr-inst-row ct-fund-row"
						class:ct-fund-row--expanded={expandedFunds.has(group.fund_key)}
						onclick={() => {
							if (group.has_classes) {
								toggleExpand(group.fund_key);
							} else {
								onSelectFund(group.representative);
							}
						}}
					>
						<td class="ct-col-expand">
							{#if group.has_classes}
								<span class="ct-chevron" class:ct-chevron--open={expandedFunds.has(group.fund_key)}>&#9654;</span>
							{/if}
						</td>
						<td class="ct-col-check"></td>
						<td>
							<span class="univ-badge {universeBadgeClass(group.representative.universe)}">
								{UNIVERSE_LABELS[group.representative.universe] ?? group.representative.universe}
							</span>
						</td>
						<td class="std-ticker">
							<span class="ticker-cell">{group.representative.ticker ?? "\u2014"}</span>
						</td>
						<td class="std-name">
							<span class="inst-name">{group.representative.name}</span>
							{#if group.has_classes}
								<span class="ct-class-count">{group.classes.length} classes</span>
							{:else if group.representative.isin}
								<span class="inst-ids">{group.representative.isin}</span>
							{/if}
						</td>
						<td class="std-manager">{group.representative.manager_name ?? "\u2014"}</td>
						<td>
							<span class="ct-type-label">{fundTypeLabel(group.representative.fund_type)}</span>
						</td>
						<td class="std-aum">{group.representative.aum ? formatAUM(group.representative.aum) : "\u2014"}</td>
						<td>{group.representative.region}</td>
						<td>
							<div class="ct-disclosure-dots">
								<span class="ct-dot" class:ct-dot--on={group.representative.disclosure.has_holdings} title="Holdings"></span>
								<span class="ct-dot" class:ct-dot--on={group.representative.disclosure.has_nav_history} title="NAV"></span>
								<span class="ct-dot" class:ct-dot--on={group.representative.disclosure.has_quant_metrics} title="Quant"></span>
								<span class="ct-dot" class:ct-dot--on={group.representative.disclosure.has_style_analysis} title="Style"></span>
							</div>
						</td>
					</tr>

					<!-- Class rows (children) — only if expanded -->
					{#if group.has_classes && expandedFunds.has(group.fund_key)}
						{#each group.classes as cls (`${cls.external_id}:${cls.class_id}`)}
							<tr
								class="scr-inst-row ct-class-row"
								class:ct-class-row--selected={isClassSelected(cls)}
							>
								<td class="ct-col-expand ct-class-indent"></td>
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
								<td class="std-ticker">
									<span class="ticker-cell">{cls.ticker ?? "\u2014"}</span>
								</td>
								<td class="std-name">
									<span class="ct-class-name">{cls.class_name ?? cls.class_id ?? "\u2014"}</span>
									{#if cls.isin}
										<span class="inst-ids">{cls.isin}</span>
									{/if}
								</td>
								<td colspan="4">
									<button
										class="ct-detail-link"
										onclick={(e) => { e.stopPropagation(); onSelectFund(cls); }}
									>
										View details &rarr;
									</button>
								</td>
								<td>
									<div class="ct-disclosure-dots">
										<span class="ct-dot" class:ct-dot--on={cls.disclosure.has_holdings} title="Holdings"></span>
										<span class="ct-dot" class:ct-dot--on={cls.disclosure.has_nav_history} title="NAV"></span>
										<span class="ct-dot" class:ct-dot--on={cls.disclosure.has_quant_metrics} title="Quant"></span>
										<span class="ct-dot" class:ct-dot--on={cls.disclosure.has_style_analysis} title="Style"></span>
									</div>
								</td>
							</tr>
						{/each}
					{/if}
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
		color: var(--ii-text-primary, #1a202c);
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
		font-family: Consolas, var(--ii-font-mono, monospace);
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

	/* ── Tree table ── */
	.ct-tree-table .ct-col-expand { width: 28px; }
	.ct-tree-table .ct-col-check  { width: 36px; text-align: center; }

	/* Fund row parent */
	.ct-fund-row { cursor: pointer; }
	.ct-fund-row--expanded { background: #f8fafc; }

	/* Chevron */
	.ct-chevron {
		display: inline-block;
		font-size: 10px;
		color: #62748e;
		transition: transform 120ms ease;
		user-select: none;
	}
	.ct-chevron--open { transform: rotate(90deg); }

	/* Class rows (children) */
	.ct-class-row { background: #fbfdff; }
	.ct-class-row:hover { background: #f0f7ff; }
	.ct-class-row--selected { background: #eff6ff !important; }
	.ct-class-indent { padding-left: 28px; }

	.ct-class-name {
		font-size: 13px;
		font-weight: 500;
		color: #374151;
	}

	/* Class count badge next to fund name */
	.ct-class-count {
		display: inline-block;
		margin-left: 8px;
		font-size: 11px;
		color: #6b7280;
		background: #f3f4f6;
		border-radius: 8px;
		padding: 1px 7px;
	}

	/* Checkbox */
	.ct-class-checkbox {
		cursor: pointer;
		width: 15px;
		height: 15px;
		accent-color: #1447e6;
	}

	/* Send to DD button (appears when selection exists) */
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

	/* Detail link inside class row */
	.ct-detail-link {
		background: none;
		border: none;
		padding: 0;
		font-size: 12px;
		color: #1447e6;
		cursor: pointer;
		text-decoration: underline;
		font-family: var(--ii-font-sans);
	}
	.ct-detail-link:hover { color: #0f3ccc; }
</style>

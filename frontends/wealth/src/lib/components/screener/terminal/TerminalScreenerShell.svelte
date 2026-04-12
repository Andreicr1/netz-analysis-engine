<!--
  TerminalScreenerShell — 3-column high-density screener grid.

  Grid topology:
    ┌──────────┬──���───────────────────┬─────────────┐
    │          │                      │             │
    │ FILTERS  │      DATA GRID       │ QUICK STATS │
    │ (280px)  │       (1fr)          │   (320px)   │
    │          │                      │             │
    └────���─────┴──────────────────��───┴──────────��──┘

  Data source: `/screener/catalog` (materialized view mv_unified_funds
  over SEC N-CEN/XBRL, ESMA Fund Register, and hedge/private fund
  tables). Filters drive the backend query directly — all filtering,
  sorting and pagination happen server-side.

  Debounced fetch (250ms) with AbortController to cancel in-flight
  requests when the user drags a slider.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import TerminalScreenerFilters, {
		type FilterState,
	} from "./TerminalScreenerFilters.svelte";
	import TerminalDataGrid, { type ScreenerAsset } from "./TerminalDataGrid.svelte";
	import TerminalScreenerQuickStats from "./TerminalScreenerQuickStats.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface Props {
		filters: FilterState;
		onFiltersChange: (filters: FilterState) => void;
	}

	let { filters, onFiltersChange }: Props = $props();

	// ── Universe labels ──────────────────────��──────────
	const FUND_TYPE_LABELS: Record<string, string> = {
		mutual_fund: "Mutual",
		etf: "ETF",
		closed_end: "CEF",
		interval_fund: "Interval",
		bdc: "BDC",
		money_market: "MMF",
		hedge_fund: "Hedge",
		private_fund: "Private",
		private_equity_fund: "PE",
		ucits: "UCITS",
		unknown: "—",
	};

	// ── Backend catalog item shape (subset we consume) ──
	interface UnifiedFundItem {
		external_id: string;
		instrument_id: string | null;
		universe: string;
		name: string;
		ticker: string | null;
		isin: string | null;
		fund_type: string;
		strategy_label: string | null;
		investment_geography: string | null;
		domicile: string | null;
		currency: string | null;
		manager_name: string | null;
		manager_id: string | null;
		aum: number | null;
		inception_date: string | null;
		expense_ratio_pct: number | null;
		avg_annual_return_1y: number | null;
		avg_annual_return_10y: number | null;
		elite_flag: boolean | null;
		in_universe: boolean;
		disclosure?: { nav_status?: string | null };
	}

	interface UnifiedCatalogPage {
		items: UnifiedFundItem[];
		total: number;
		page: number;
		page_size: number;
		has_next: boolean;
	}

	function toAsset(raw: UnifiedFundItem): ScreenerAsset {
		return {
			id: raw.external_id,
			instrumentId: raw.instrument_id,
			ticker: raw.ticker,
			name: raw.name,
			fundType: raw.fund_type,
			universeLabel: FUND_TYPE_LABELS[raw.fund_type] ?? raw.fund_type,
			strategy: raw.strategy_label,
			geography: raw.investment_geography,
			domicile: raw.domicile,
			currency: raw.currency,
			managerName: raw.manager_name,
			managerId: raw.manager_id,
			aum: raw.aum,
			expenseRatioPct: raw.expense_ratio_pct,
			ret1y: raw.avg_annual_return_1y,
			ret10y: raw.avg_annual_return_10y,
			inceptionDate: raw.inception_date,
			isin: raw.isin,
			navStatus: raw.disclosure?.nav_status ?? null,
			eliteFlag: raw.elite_flag === true,
			inUniverse: raw.in_universe === true,
		};
	}

	// ── State ───────────────────────────────────────────
	let assets = $state<ScreenerAsset[]>([]);
	let total = $state(0);
	let loading = $state(false);
	let errorMessage = $state<string | null>(null);
	let selectedId = $state<string | null>(null);
	let highlightedIndex = $state(-1);

	const selectedAsset = $derived<ScreenerAsset | null>(
		assets.find((a) => a.id === selectedId) ?? null,
	);

	// ── Query builder ──────────────���────────────────────
	function buildQuery(f: FilterState): Record<string, string> {
		const q: Record<string, string> = {
			page: "1",
			page_size: "200",
			sort: "aum_desc",
		};
		if (f.onlyWithNav) q.in_universe = "true";
		if (f.eliteOnly) q.elite_only = "true";
		if (f.fundUniverse.size > 0) q.fund_universe = [...f.fundUniverse].join(",");
		if (f.strategies.size > 0) q.strategy_label = [...f.strategies].join(",");
		if (f.geographies.size > 0) q.investment_geography = [...f.geographies].join(",");
		if (f.aumMin > 0) q.aum_min = String(f.aumMin);
		if (f.returnMin > -999) q.min_return_1y = String(f.returnMin);
		if (f.expenseMax < 10) q.max_expense_ratio = String(f.expenseMax);
		return q;
	}

	// ── Debounced reactive fetch ────────────────────────
	let debounceHandle: ReturnType<typeof setTimeout> | null = null;
	let currentFetchId = 0;

	$effect(() => {
		// Track filters to trigger re-runs on any change
		const snapshot = buildQuery(filters);

		if (debounceHandle) clearTimeout(debounceHandle);
		debounceHandle = setTimeout(async () => {
			const fetchId = ++currentFetchId;
			loading = true;
			errorMessage = null;

			try {
				const page = await api.get<UnifiedCatalogPage>("/screener/catalog", snapshot);
				if (fetchId !== currentFetchId) return; // stale
				assets = page.items.map(toAsset);
				total = page.total;

				// Drop selection if it fell out of the current result set
				if (selectedId && !assets.some((a) => a.id === selectedId)) {
					selectedId = null;
				}
			} catch (err) {
				if (fetchId !== currentFetchId) return;
				assets = [];
				total = 0;
				errorMessage = err instanceof Error ? err.message : "Failed to load catalog";
			} finally {
				if (fetchId === currentFetchId) loading = false;
			}
		}, 250);

		return () => {
			if (debounceHandle) clearTimeout(debounceHandle);
		};
	});

	function handleSelect(asset: ScreenerAsset) {
		selectedId = asset.id;
	}

	function handleHighlight(index: number) {
		highlightedIndex = index;
	}
</script>

<div class="ts-root">
	<div class="ts-zone ts-filters" aria-label="Screener filters">
		<TerminalScreenerFilters {filters} {onFiltersChange} />
	</div>
	<div class="ts-zone ts-datagrid" aria-label="Instrument data grid">
		<TerminalDataGrid
			{assets}
			{total}
			{loading}
			{errorMessage}
			{selectedId}
			{highlightedIndex}
			onSelect={handleSelect}
			onHighlight={handleHighlight}
		/>
	</div>
	<div class="ts-zone ts-stats" aria-label="Quick stats">
		<TerminalScreenerQuickStats asset={selectedAsset} />
	</div>
</div>

<style>
	.ts-root {
		display: grid;
		grid-template-areas: "filters datagrid stats";
		grid-template-columns: 280px 1fr 320px;
		grid-template-rows: 100%;
		gap: 2px;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: #000000;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.ts-zone {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	.ts-filters { grid-area: filters; }
	.ts-datagrid { grid-area: datagrid; }
	.ts-stats { grid-area: stats; }
</style>

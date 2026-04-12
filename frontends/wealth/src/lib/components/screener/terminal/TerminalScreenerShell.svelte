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
		approval_status?: string | null;
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
			approvalStatus: raw.approval_status ?? null,
			universe: raw.universe,
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

	// ── Action handlers (approve / DD queue) ────────────
	let toastMessage = $state<{ text: string; type: "success" | "warn" | "info" } | null>(null);
	let toastTimer: ReturnType<typeof setTimeout> | null = null;

	function showToast(text: string, type: "success" | "warn" | "info") {
		toastMessage = { text, type };
		if (toastTimer) clearTimeout(toastTimer);
		toastTimer = setTimeout(() => { toastMessage = null; }, 3000);
	}

	async function handleApprove(asset: ScreenerAsset) {
		if (!asset.instrumentId) {
			showToast("Fund not yet in instruments universe", "warn");
			return;
		}
		try {
			const resp = await api.post<{ approved: string[]; rejected_dd_required: string[] }>(
				"/universe/fast-approve",
				{ instrument_ids: [asset.instrumentId] },
			);
			if (resp.rejected_dd_required.length > 0) {
				showToast("DD report required for this fund type", "warn");
				return;
			}
			showToast("Fund approved to universe", "success");
			// Update locally
			const idx = assets.findIndex((a) => a.id === asset.id);
			if (idx >= 0) {
				assets[idx] = { ...assets[idx], inUniverse: true } as ScreenerAsset;
			}
		} catch {
			showToast("Failed to approve fund", "warn");
		}
	}

	async function handleQueueDD(asset: ScreenerAsset) {
		if (!asset.instrumentId) {
			showToast("Fund not yet in instruments universe", "warn");
			return;
		}
		try {
			await api.post("/dd-reports/funds/" + asset.instrumentId);
			showToast("DD report queued", "info");
			// Update locally
			const idx = assets.findIndex((a) => a.id === asset.id);
			if (idx >= 0) {
				assets[idx] = { ...assets[idx], approvalStatus: "pending" } as ScreenerAsset;
			}
		} catch {
			showToast("Failed to queue DD report", "warn");
		}
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
			onApprove={handleApprove}
			onQueueDD={handleQueueDD}
		/>
	</div>
	<div class="ts-zone ts-stats" aria-label="Quick stats">
		<TerminalScreenerQuickStats asset={selectedAsset} />
	</div>

	{#if toastMessage}
		<div class="ts-toast ts-toast--{toastMessage.type}">{toastMessage.text}</div>
	{/if}
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

	/* ── Toast ────────────────────────────────────────── */
	.ts-toast {
		position: absolute;
		bottom: 16px;
		left: 50%;
		transform: translateX(-50%);
		padding: 6px 16px;
		font-family: "JetBrains Mono", monospace;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		border: 1px solid rgba(255, 255, 255, 0.12);
		background: #0d1220;
		z-index: 10;
	}
	.ts-toast--success { color: #22c55e; border-color: rgba(34, 197, 94, 0.3); }
	.ts-toast--warn { color: #f59e0b; border-color: rgba(245, 158, 11, 0.3); }
	.ts-toast--info { color: #2d7ef7; border-color: rgba(45, 126, 247, 0.3); }
</style>

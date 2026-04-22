<!--
  TerminalScreenerShell — 2-column high-density screener grid.

  Grid topology:
    ┌──────────┬─────────────────────────────────────┐
    │          │                                     │
    │ FILTERS  │            DATA GRID                │
    │ (280px)  │             (1fr)                   │
    │          │                                     │
    └──────────┴─────────────────────────────────────┘

  Data source: `/screener/catalog` (materialized view mv_unified_funds
  over SEC N-CEN/XBRL, ESMA Fund Register, and hedge/private fund
  tables). Filters drive the backend query directly — all filtering,
  sorting and pagination happen server-side.

  Debounced fetch (250ms) with AbortController to cancel in-flight
  requests when the user drags a slider.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { SvelteMap } from "svelte/reactivity";
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { createClientApiClient } from "../../api/client";
	import TerminalScreenerFilters, {
		type FilterState,
	} from "./TerminalScreenerFilters.svelte";
	import TerminalDataGrid, { type ScreenerAsset } from "./TerminalDataGrid.svelte";
	import FilterChipRow from "./FilterChipRow.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	const HREF_BUILDER = `${base}/portfolio/builder`;

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
		manager_score: number | null;
		blended_momentum_score: number | null;
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
		next_cursor: string | null;
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
			expenseRatioPct: raw.expense_ratio_pct != null ? raw.expense_ratio_pct * 100 : null,
			ret1y: raw.avg_annual_return_1y != null ? raw.avg_annual_return_1y * 100 : null,
			ret10y: raw.avg_annual_return_10y != null ? raw.avg_annual_return_10y * 100 : null,
			managerScore: raw.manager_score,
			blendedMomentumScore: raw.blended_momentum_score,
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

	// ── Infinite scroll state ────────────────────────────
	let nextCursor = $state<string | null>(null);
	let isLoadingMore = $state(false);
	/** Generation counter — increments on every fresh fetch (filter change). */
	let fetchGeneration = $state(0);

	// ── Sparkline batch fetch ───────────────────────────
	/**
	 * Keyed by instrument_id (UUID). Populated after each catalog fetch
	 * from POST /screener/sparklines. Passed down to TerminalDataGrid;
	 * the grid's MiniSparkline column reads by row.instrumentId.
	 *
	 * Stored as a Map (not a plain Record) so the prop reference
	 * changes when the fetch completes — triggers downstream $derived
	 * reactivity cleanly.
	 */
	let sparklineMap = $state<Map<string, number[]>>(new Map());
	let sparklineFetchId = 0;

	interface SparklineResponsePoint {
		month: string;
		nav_close: number;
		return_1m?: number | null;
	}

	async function refreshSparklines(currentAssets: ScreenerAsset[]) {
		const ids = currentAssets
			.map((a) => a.instrumentId)
			.filter((id): id is string => id !== null);
		if (ids.length === 0) {
			sparklineMap = new Map();
			return;
		}
		const fetchId = ++sparklineFetchId;
		// Endpoint caps at 100 IDs per call; chunk in parallel and merge.
		const CHUNK = 100;
		const chunks: string[][] = [];
		for (let i = 0; i < ids.length; i += CHUNK) {
			chunks.push(ids.slice(i, i + CHUNK));
		}
		try {
			const results = await Promise.all(
				chunks.map((chunk) =>
					api.post<Record<string, SparklineResponsePoint[]>>(
						"/screener/sparklines",
						{ instrument_ids: chunk, months: 12 },
					),
				),
			);
			if (fetchId !== sparklineFetchId) return; // stale
			const next = new SvelteMap<string, number[]>();
			for (const chunkResult of results) {
				for (const [iid, points] of Object.entries(chunkResult)) {
					if (!Array.isArray(points) || points.length < 2) continue;
					next.set(
						iid,
						points.map((p) => p.nav_close),
					);
				}
			}
			sparklineMap = next;
		} catch {
			// Non-fatal: sparklines are decorative — MiniSparkline renders
			// empty svg when no data is present.
		}
	}


	// ── Query builder ──────────────���────────────────────
	function buildQuery(f: FilterState): Record<string, string> {
		const q: Record<string, string> = {
			page: "1",
			page_size: "200",
			sort: "aum_desc",
			in_universe: "true", // Always filter to NAV-populated funds — non-negotiable data-quality gate
		};
		if (f.eliteOnly) q.elite_only = "true";
		if (f.fundUniverse.size > 0) q.fund_universe = [...f.fundUniverse].join(",");
		if (f.strategies.size > 0) q.strategy_label = [...f.strategies].join(",");
		if (f.geographies.size > 0) q.investment_geography = [...f.geographies].join(",");
		if (f.aumMin > 0) q.aum_min = String(f.aumMin);
		if (f.aumMax > 0) q.aum_max = String(f.aumMax);
		if (f.returnMin > -999) q.min_return_1y = String(f.returnMin);
		if (f.returnMax < 999) q.return_1y_max = String(f.returnMax / 100);
		if (f.expenseMax < 10) q.max_expense_ratio = String(f.expenseMax);
		if (f.managerNames.length > 0) q.manager_names = f.managerNames.join(",");

		// Expanded metric filters
		if (f.sharpeMin) q.sharpe_min = f.sharpeMin;
		if (f.sharpeMax) q.sharpe_max = f.sharpeMax;
		if (f.volatilityMax) q.volatility_max = f.volatilityMax;
		if (f.return10yMin) q.return_10y_min = f.return10yMin;
		if (f.return10yMax) q.return_10y_max = f.return10yMax;

		// Drawdown: user enters positive % (e.g. 15 = 15%), backend expects negative decimal
		// "No worse than 15%" → max_drawdown_min = -0.15 (floor)
		// "At least 5% drawdown" → max_drawdown_max = -0.05 (ceiling)
		if (f.drawdownMaxPct) q.max_drawdown_min = String(-Math.abs(+f.drawdownMaxPct) / 100);
		if (f.drawdownMinPct) q.max_drawdown_max = String(-Math.abs(+f.drawdownMinPct) / 100);

		return q;
	}

	// ── Debounced reactive fetch ────────────────────────
	let debounceHandle: ReturnType<typeof setTimeout> | null = null;
	let currentFetchId = 0;
	let retryTrigger = $state(0);

	function retryFetch() {
		errorMessage = null;
		retryTrigger++;
	}

	$effect(() => {
		// Track filters + retryTrigger to trigger re-runs
		const snapshot = buildQuery(filters);
		void retryTrigger; // reactive dependency for retry

		if (debounceHandle) clearTimeout(debounceHandle);
		debounceHandle = setTimeout(async () => {
			const fetchId = ++currentFetchId;
			loading = true;
			errorMessage = null;
			// Reset infinite scroll state on fresh fetch
			nextCursor = null;
			isLoadingMore = false;
			fetchGeneration++;

			try {
				const page = await api.get<UnifiedCatalogPage>("/screener/catalog", snapshot);
				if (fetchId !== currentFetchId) return; // stale
				assets = page.items.map(toAsset);
				total = page.total;
				nextCursor = page.next_cursor;

				// Drop selection if it fell out of the current result set
				if (selectedId && !assets.some((a) => a.id === selectedId)) {
					selectedId = null;
				}

				// Fire-and-forget sparkline fetch — decorative overlay,
				// must not block the catalog render.
				void refreshSparklines(assets);
			} catch (err) {
				if (fetchId !== currentFetchId) return;
				assets = [];
				total = 0;
				nextCursor = null;
				const raw = err instanceof Error ? err.message : "Failed to load catalog";
				// Truncate verbose backend tracebacks to first meaningful line
				const firstLine = raw.split("\n")[0] ?? raw;
				errorMessage = firstLine.length > 200 ? firstLine.slice(0, 200) + "..." : firstLine;
			} finally {
				if (fetchId === currentFetchId) loading = false;
			}
		}, 250);

		return () => {
			if (debounceHandle) clearTimeout(debounceHandle);
		};
	});

	// ── Infinite scroll: load next page ─────────────────
	async function loadMore() {
		if (!nextCursor || isLoadingMore || loading) return;
		isLoadingMore = true;
		try {
			const snapshot = buildQuery(filters);
			snapshot.cursor = nextCursor;
			delete snapshot.page; // keyset mode — no offset
			const page = await api.get<UnifiedCatalogPage>("/screener/catalog", snapshot);
			const newAssets = page.items.map(toAsset);
			assets = [...assets, ...newAssets];
			// Keep the initial total (page 1) — keyset cursor changes the
			// windowed count on subsequent pages due to WHERE clause shift.
			nextCursor = page.next_cursor;
			// Refresh sparkline map for the combined asset set.
			void refreshSparklines(assets);
		} catch {
			// Non-fatal: user can keep scrolling to retry
		} finally {
			isLoadingMore = false;
		}
	}

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

	// ── DataGrid ref for scrollToIndex ──────────────────
	let dataGridRef: TerminalDataGrid | undefined = $state();
	let filtersEl: HTMLDivElement | undefined = $state();
	let rootEl: HTMLDivElement | undefined = $state();

	// ── Keyboard shortcuts ──────────────────────────────
	function handleKeydown(e: KeyboardEvent) {
		// Don't fire when typing in inputs
		const target = e.target as HTMLElement;
		if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") {
			if (e.key === "Escape") {
				target.blur();
				e.preventDefault();
			}
			return;
		}

		switch (e.key) {
			case "/": {
				e.preventDefault();
				// Focus first interactive element in filter panel
				const input = filtersEl?.querySelector("input, button");
				if (input instanceof HTMLElement) input.focus();
				break;
			}
			case "ArrowDown": {
				e.preventDefault();
				const next = Math.min(highlightedIndex + 1, assets.length - 1);
				highlightedIndex = next;
				dataGridRef?.scrollToIndex(next);
				break;
			}
			case "ArrowUp": {
				e.preventDefault();
				const prev = Math.max(highlightedIndex - 1, 0);
				highlightedIndex = prev;
				dataGridRef?.scrollToIndex(prev);
				break;
			}
			case "Enter": {
				if (highlightedIndex >= 0 && highlightedIndex < assets.length) {
					const asset = assets[highlightedIndex];
					if (asset) {
						selectedId = asset.id;
						// Dispatch focustrigger event for FocusMode (bubbles to page)
						rootEl?.dispatchEvent(
							new CustomEvent("focustrigger", {
								bubbles: true,
								detail: { entityKind: "fund", entityId: asset.id, entityLabel: asset.name },
							}),
						);
					}
				}
				break;
			}
			case "u": {
				if (highlightedIndex >= 0 && highlightedIndex < assets.length) {
					const asset = assets[highlightedIndex];
					if (asset && !asset.inUniverse && asset.approvalStatus !== "pending") {
						handleApprove(asset);
					}
				}
				break;
			}
			case "d": {
				if (highlightedIndex >= 0 && highlightedIndex < assets.length) {
					const asset = assets[highlightedIndex];
					if (asset && !asset.inUniverse && asset.approvalStatus !== "pending") {
						handleQueueDD(asset);
					}
				}
				break;
			}
			case "e": {
				e.preventDefault();
				onFiltersChange({ ...filters, eliteOnly: !filters.eliteOnly });
				break;
			}
			case "b": {
				if (highlightedIndex >= 0 && highlightedIndex < assets.length) {
					const asset = assets[highlightedIndex];
					if (asset && asset.inUniverse) {
						goto(HREF_BUILDER);
					} else {
						showToast("Fund must be approved to universe first", "warn");
					}
				}
				break;
			}
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

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="ts-root" onkeydown={handleKeydown} bind:this={rootEl}>
	<div class="ts-zone ts-filters" aria-label="Screener filters" bind:this={filtersEl}>
		<TerminalScreenerFilters {filters} {onFiltersChange} />
	</div>
	<div class="ts-zone ts-datagrid" aria-label="Instrument data grid">
		{#if errorMessage}
			<div class="sep-panel">
				<div class="sep-header">
					<span class="sep-code">[ ERR ]</span>
					<span class="sep-title">SCREENER DATA ERROR</span>
				</div>
				<div class="sep-body">
					<p class="sep-message">{errorMessage}</p>
					<p class="sep-hint">The screener encountered a data error. This may be caused by a backend timeout, a malformed response, or a network issue.</p>
				</div>
				<div class="sep-actions">
					<button class="sep-btn" onclick={retryFetch}>[ RETRY ]</button>
					<button class="sep-btn sep-btn--reload" onclick={() => location.reload()}>[ RELOAD PAGE ]</button>
				</div>
			</div>
		{:else}
			<FilterChipRow {filters} {onFiltersChange} />
			<svelte:boundary>
				<TerminalDataGrid
					bind:this={dataGridRef}
					{assets}
					{total}
					{loading}
					errorMessage={null}
					{selectedId}
					{highlightedIndex}
					{isLoadingMore}
					hasMore={nextCursor !== null}
					{fetchGeneration}
					{sparklineMap}
					onSelect={handleSelect}
					onHighlight={handleHighlight}
					onApprove={handleApprove}
					onQueueDD={handleQueueDD}
					onLoadMore={loadMore}
				/>
				{#snippet failed(error, reset)}
					<div class="sep-panel">
						<div class="sep-header">
							<span class="sep-code">[ ERR ]</span>
							<span class="sep-title">SCREENER RENDER ERROR</span>
						</div>
						<div class="sep-body">
							<p class="sep-message">{(error as Error)?.message ?? "An unexpected rendering error occurred"}</p>
							<p class="sep-hint">The screener grid encountered a rendering crash. Try retrying or reloading the page.</p>
						</div>
						<div class="sep-actions">
							<button class="sep-btn" onclick={reset}>[ RETRY ]</button>
							<button class="sep-btn sep-btn--reload" onclick={() => location.reload()}>[ RELOAD PAGE ]</button>
						</div>
					</div>
				{/snippet}
			</svelte:boundary>
		{/if}
	</div>

	{#if toastMessage}
		<div class="ts-toast ts-toast--{toastMessage.type}">{toastMessage.text}</div>
	{/if}
</div>

<style>
	.ts-root {
		display: grid;
		grid-template-areas: "filters datagrid";
		grid-template-columns: 280px 1fr;
		grid-template-rows: 1fr;
		gap: 2px;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
	}

	.ts-zone {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	.ts-filters { grid-area: filters; }
	.ts-datagrid {
		grid-area: datagrid;
		display: flex;
		flex-direction: column;
	}
	.ts-datagrid :global(> *) {
		flex-shrink: 0;
	}
	.ts-datagrid :global(> .dg-root) {
		flex: 1 1 auto;
		min-height: 0;
	}

	/* ── Error panel ─────────────────────────────────── */
	.sep-panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: var(--terminal-space-6, 24px);
		padding: var(--terminal-space-6, 24px);
		font-family: var(--terminal-font-mono, "JetBrains Mono", monospace);
		color: var(--terminal-status-error, #ef4444);
	}

	.sep-header {
		display: flex;
		align-items: baseline;
		gap: var(--terminal-space-3, 12px);
	}

	.sep-code {
		font-size: var(--terminal-text-20, 20px);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps, 0.06em);
	}

	.sep-title {
		font-size: var(--terminal-text-14, 14px);
		letter-spacing: var(--terminal-tracking-caps, 0.06em);
		color: var(--terminal-fg-secondary, #8a94a6);
	}

	.sep-body {
		text-align: center;
		max-width: 480px;
	}

	.sep-message {
		font-size: var(--terminal-text-11, 11px);
		color: var(--terminal-fg-primary, #e2e8f0);
		margin: 0 0 var(--terminal-space-2, 8px);
	}

	.sep-hint {
		font-size: var(--terminal-text-11, 11px);
		color: var(--terminal-fg-tertiary, #5a6577);
		margin: 0;
	}

	.sep-actions {
		display: flex;
		gap: var(--terminal-space-4, 16px);
	}

	.sep-btn {
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: 0;
		color: var(--terminal-fg-primary, #e2e8f0);
		font-family: var(--terminal-font-mono, "JetBrains Mono", monospace);
		font-size: var(--terminal-text-11, 11px);
		letter-spacing: var(--terminal-tracking-caps, 0.06em);
		padding: var(--terminal-space-2, 8px) var(--terminal-space-4, 16px);
		cursor: pointer;
	}

	.sep-btn:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.sep-btn--reload:hover {
		border-color: var(--terminal-status-warn, #f59e0b);
		color: var(--terminal-status-warn, #f59e0b);
	}

	/* ── Toast ────────────────────────────────────────── */
	.ts-toast {
		position: absolute;
		bottom: 16px;
		left: 50%;
		transform: translateX(-50%);
		padding: 6px 16px;
		font-family: var(--terminal-font-mono);
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-overlay);
		z-index: 10;
	}
	.ts-toast--success { color: var(--terminal-status-success); border-color: color-mix(in srgb, var(--terminal-status-success) 30%, transparent); }
	.ts-toast--warn { color: var(--terminal-accent-amber); border-color: color-mix(in srgb, var(--terminal-accent-amber) 30%, transparent); }
	.ts-toast--info { color: var(--terminal-accent-cyan); border-color: color-mix(in srgb, var(--terminal-accent-cyan) 30%, transparent); }
</style>

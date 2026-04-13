<!--
  TerminalDataGrid — virtualized high-density scrollable catalog grid.
  CSS Grid layout with role="grid" ARIA for accessibility.
  Only renders visible rows (~50) from a potentially 9k+ dataset.
  Fixed ROW_HEIGHT=32px, overscan buffer of 5 rows above/below viewport.
-->
<script module lang="ts">
	export interface ScreenerAsset {
		id: string;                 // external_id from /screener/catalog
		/**
		 * Global instruments_universe UUID. Populated by the backend via
		 * ticker/ISIN lookup when the fund has NAV history; null for
		 * rows not yet imported into instruments_universe.
		 */
		instrumentId: string | null;
		ticker: string | null;
		name: string;
		fundType: string;           // raw fund_type key
		universeLabel: string;      // pretty label for fund_type
		strategy: string | null;    // strategy_label
		geography: string | null;   // investment_geography
		domicile: string | null;
		currency: string | null;
		managerName: string | null;
		managerId: string | null;
		aum: number | null;
		expenseRatioPct: number | null;  // Already in human % (0.85 = 0.85%)
		ret1y: number | null;            // Already in human % (5.0 = 5%)
		ret10y: number | null;           // Already in human % (8.0 = 8%)
		managerScore: number | null;     // Composite score 0-100
		inceptionDate: string | null;
		isin: string | null;
		navStatus: string | null;   // available | pending_import | unavailable | null
		eliteFlag: boolean;
		inUniverse: boolean;
		approvalStatus?: string | null;
		universe?: string | null;
	}
</script>

<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber, readTerminalTokens } from "@investintell/ui";
	import { focusTrigger } from "$lib/components/terminal/focus-mode/focus-trigger";
	import { createClientApiClient } from "$lib/api/client";

	const ROW_HEIGHT = 32;
	const OVERSCAN = 5;
	const SPARKLINE_W = 48;
	const SPARKLINE_H = 16;

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface Props {
		assets: ScreenerAsset[];
		total: number;
		loading: boolean;
		errorMessage: string | null;
		selectedId: string | null;
		highlightedIndex: number;
		isLoadingMore: boolean;
		hasMore: boolean;
		fetchGeneration: number;
		onSelect: (asset: ScreenerAsset) => void;
		onHighlight: (index: number) => void;
		onApprove: (asset: ScreenerAsset) => Promise<void>;
		onQueueDD: (asset: ScreenerAsset) => Promise<void>;
		onLoadMore: () => void;
	}

	let {
		assets,
		total,
		loading,
		errorMessage,
		selectedId,
		highlightedIndex,
		isLoadingMore,
		hasMore,
		fetchGeneration,
		onSelect,
		onHighlight,
		onApprove,
		onQueueDD,
		onLoadMore,
	}: Props = $props();

	// ── Type badge map ────────────────────────────────
	const TYPE_BADGES: Record<string, { label: string; title: string }> = {
		mutual_fund:  { label: "MF",    title: "Mutual Fund" },
		registered_us: { label: "MF",   title: "Mutual Fund" },
		etf:          { label: "ETF",   title: "Exchange-Traded Fund" },
		closed_end:   { label: "CEF",   title: "Closed-End Fund" },
		interval_fund: { label: "INT",  title: "Interval Fund" },
		bdc:          { label: "BDC",   title: "Business Development Company" },
		money_market: { label: "MMF",   title: "Money Market Fund" },
		hedge_fund:   { label: "HF",    title: "Hedge Fund" },
		private_fund: { label: "PRIV",  title: "Private Fund" },
		private_equity_fund: { label: "PE", title: "Private Equity Fund" },
		ucits:        { label: "UCITS", title: "UCITS (European)" },
		ucits_eu:     { label: "UCITS", title: "UCITS (European)" },
	};

	function getTypeBadge(asset: ScreenerAsset): { label: string; title: string } {
		return TYPE_BADGES[asset.universe ?? asset.fundType] ?? TYPE_BADGES[asset.fundType] ?? { label: asset.universeLabel, title: asset.fundType };
	}

	// ── Action column state ────────────────────────────
	const LIQUID_UNIVERSES = new Set(["registered_us", "etf", "ucits_eu", "money_market"]);
	let actionPending = $state(new Set<string>());

	// ── Virtual scroll state ───────────────────────────
	let scrollContainer: HTMLDivElement | undefined = $state();
	let viewportHeight = $state(600);
	let scrollTop = $state(0);

	const totalHeight = $derived(assets.length * ROW_HEIGHT);
	const visibleCount = $derived(Math.ceil(viewportHeight / ROW_HEIGHT));
	const startIndex = $derived(Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN));
	const endIndex = $derived(
		Math.min(assets.length, Math.floor(scrollTop / ROW_HEIGHT) + visibleCount + OVERSCAN),
	);
	const visibleAssets = $derived(assets.slice(startIndex, endIndex));
	const offsetY = $derived(startIndex * ROW_HEIGHT);

	let loadMoreDebounce: ReturnType<typeof setTimeout> | null = null;

	function handleScroll() {
		if (!scrollContainer) return;
		scrollTop = scrollContainer.scrollTop;

		// Infinite scroll: load more when within 5 rows of the data boundary
		const distanceFromBottom = scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight;
		const threshold = ROW_HEIGHT * 5;
		if (distanceFromBottom < threshold && hasMore && !isLoadingMore) {
			if (loadMoreDebounce) clearTimeout(loadMoreDebounce);
			loadMoreDebounce = setTimeout(() => onLoadMore(), 100);
		}
	}

	// Measure viewport height on mount and resize
	$effect(() => {
		if (!scrollContainer) return;
		const ro = new ResizeObserver((entries) => {
			for (const entry of entries) {
				viewportHeight = entry.contentRect.height;
			}
		});
		ro.observe(scrollContainer);
		viewportHeight = scrollContainer.clientHeight;
		return () => ro.disconnect();
	});

	// Scroll to highlighted row when it changes (keyboard navigation)
	export function scrollToIndex(index: number) {
		if (!scrollContainer || index < 0 || index >= assets.length) return;
		const rowTop = index * ROW_HEIGHT;
		const rowBottom = rowTop + ROW_HEIGHT;
		const viewTop = scrollContainer.scrollTop;
		const viewBottom = viewTop + viewportHeight;
		if (rowTop < viewTop) {
			scrollContainer.scrollTop = rowTop;
		} else if (rowBottom > viewBottom) {
			scrollContainer.scrollTop = rowBottom - viewportHeight;
		}
	}

	// Reset scroll only on filter change (new generation), NOT on append
	$effect(() => {
		void fetchGeneration;
		if (scrollContainer) {
			scrollContainer.scrollTop = 0;
			scrollTop = 0;
		}
	});

	// ── Formatters ─────────────────────────────────────
	function fmtPct(v: number | null, decimals: number = 2): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals) + "%";
	}

	function fmtNum(v: number | null, decimals: number = 2): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals);
	}

	function fmtAum(v: number | null): string {
		if (v == null || v <= 0) return "\u2014";
		if (v >= 1e12) return formatNumber(v / 1e12, 2) + "T";
		if (v >= 1e9) return formatNumber(v / 1e9, 1) + "B";
		if (v >= 1e6) return formatNumber(v / 1e6, 0) + "M";
		return formatNumber(v, 0);
	}

	function retClass(v: number | null): string {
		if (v == null) return "";
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}

	// ── Sparkline rendering ────────────────────────────
	interface SparklinePoint {
		month: string;
		nav_close: number;
	}

	let sparklineCache = $state(new Map<string, number[]>());
	let sparklineDebounce: ReturnType<typeof setTimeout> | null = null;
	let lastFetchedIds = "";

	function drawSparkline(canvas: HTMLCanvasElement, values: number[]) {
		const ctx = canvas.getContext("2d");
		if (!ctx || values.length < 2) return;

		const dpr = window.devicePixelRatio || 1;
		canvas.width = SPARKLINE_W * dpr;
		canvas.height = SPARKLINE_H * dpr;
		ctx.scale(dpr, dpr);
		ctx.clearRect(0, 0, SPARKLINE_W, SPARKLINE_H);

		const min = Math.min(...values);
		const max = Math.max(...values);
		const range = max - min || 1;
		const step = SPARKLINE_W / (values.length - 1);

		// Color: green if positive trend, red if negative
		const last = values[values.length - 1] ?? 0;
		const first = values[0] ?? 0;
		const delta = last - first;
		const tk = readTerminalTokens();
		ctx.strokeStyle = delta > 0 ? tk.statusSuccess : delta < 0 ? tk.statusError : tk.fgTertiary;
		ctx.lineWidth = 1;
		ctx.beginPath();
		for (let i = 0; i < values.length; i++) {
			const x = Math.round(i * step);
			const v = values[i] ?? 0;
			const y = Math.round(SPARKLINE_H - ((v - min) / range) * (SPARKLINE_H - 2) - 1);
			if (i === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		}
		ctx.stroke();
	}

	// Sparkline use:action for canvas elements
	function sparklineAction(canvas: HTMLCanvasElement, instrumentId: string | null) {
		function render() {
			if (!instrumentId) return;
			const values = sparklineCache.get(instrumentId);
			if (values && values.length >= 2) {
				drawSparkline(canvas, values);
			}
		}
		render();
		return {
			update(newId: string | null) {
				instrumentId = newId;
				render();
			},
			destroy() {},
		};
	}

	// Sparkline batch fetch removed from DataGrid — SCORE column replaced
	// sparkline rendering. The drawSparkline() function and sparklineAction()
	// are kept for other consumers (FocusMode vitrine, portfolio workbench).
</script>

<div class="dg-root">
	<!-- Header row (sticky, outside scroll container) -->
	<div class="dg-header" role="row" aria-rowindex={1}>
		<span class="dg-th dg-col-ticker">Ticker</span>
		<span class="dg-th dg-col-name">Name</span>
		<span class="dg-th dg-col-type">Type</span>
		<span class="dg-th dg-col-strategy">Strategy</span>
		<span class="dg-th dg-col-geo">Geo</span>
		<span class="dg-th dg-col-aum dg-right">AUM</span>
		<span class="dg-th dg-col-ret dg-right">1Y Ret</span>
		<span class="dg-th dg-col-ret dg-right">10Y Ret</span>
		<span class="dg-th dg-col-er dg-right">ER%</span>
		<span class="dg-th dg-col-score dg-right">Score</span>
		<span class="dg-th dg-col-action dg-center">Action</span>
	</div>

	<!-- Virtualized scroll area -->
	<div
		class="dg-scroll"
		role="grid"
		aria-rowcount={assets.length + 1}
		aria-label="Screener instrument grid"
		bind:this={scrollContainer}
		onscroll={handleScroll}
		tabindex={0}
	>
		<!-- Spacer for total scroll height + indicator -->
		<div class="dg-spacer" style="height: {totalHeight + (assets.length > 0 ? 24 : 0)}px;">
			<!-- Positioned visible rows -->
			<div class="dg-rows" style="transform: translateY({offsetY}px);">
				{#each visibleAssets as asset, vi (asset.id)}
					{@const globalIndex = startIndex + vi}
					<div
						class="dg-row"
						class:selected={selectedId === asset.id}
						class:highlighted={highlightedIndex === globalIndex}
						class:zebra={globalIndex % 2 === 1}
						role="row"
						aria-rowindex={globalIndex + 2}
						aria-selected={selectedId === asset.id}
						style="height: {ROW_HEIGHT}px;"
						use:focusTrigger={{ entityKind: "fund", entityId: asset.id, entityLabel: asset.name }}
						onclick={() => onSelect(asset)}
					>
						<span class="dg-td dg-col-ticker dg-ticker" title={asset.ticker ?? asset.isin ?? ""}>
							{asset.ticker ?? asset.isin ?? "\u2014"}
						</span>
						<span class="dg-td dg-col-name dg-name" title={asset.name}>{asset.name}</span>
						<span class="dg-td dg-col-type">
							<span class="dg-type-badges">
								<span class="dg-type-badge" title={getTypeBadge(asset).title}>{getTypeBadge(asset).label}</span>
								{#if asset.eliteFlag}<span class="dg-elite-inline" title="ELITE — top in strategy">ELITE</span>{/if}
							</span>
						</span>
						<span class="dg-td dg-col-strategy dg-strategy" title={asset.strategy ?? ""}>
							{asset.strategy ?? "\u2014"}
						</span>
						<span class="dg-td dg-col-geo dg-geo">{asset.geography ?? "\u2014"}</span>
						<span class="dg-td dg-col-aum dg-right dg-num">{fmtAum(asset.aum)}</span>
						<span class="dg-td dg-col-ret dg-right dg-num {retClass(asset.ret1y)}">{fmtPct(asset.ret1y)}</span>
						<span class="dg-td dg-col-ret dg-right dg-num {retClass(asset.ret10y)}">{fmtPct(asset.ret10y)}</span>
						<span class="dg-td dg-col-er dg-right dg-num">{fmtPct(asset.expenseRatioPct)}</span>
						<span class="dg-td dg-col-score dg-right dg-num"
							class:score-high={asset.managerScore != null && asset.managerScore >= 70}
							class:score-mid={asset.managerScore != null && asset.managerScore >= 40 && asset.managerScore < 70}
							class:score-low={asset.managerScore != null && asset.managerScore < 40}
						>
							{asset.managerScore != null ? fmtNum(asset.managerScore, 1) : "\u2014"}
						</span>
						<span class="dg-td dg-col-action dg-center">
							{#if asset.inUniverse}
								<span class="dg-action-label dg-action-approved">APPROVED</span>
							{:else if asset.approvalStatus === "pending" || actionPending.has(asset.id)}
								<span class="dg-action-label dg-action-pending">PENDING</span>
							{:else if LIQUID_UNIVERSES.has(asset.universe ?? asset.fundType)}
								<button
									class="dg-action-btn dg-action-approve"
									onclick={async (e) => {
										e.stopPropagation();
										actionPending = new Set([...actionPending, asset.id]);
										await onApprove(asset);
									}}
								>
									APPROVE
								</button>
							{:else}
								<button
									class="dg-action-btn dg-action-dd"
									onclick={async (e) => {
										e.stopPropagation();
										actionPending = new Set([...actionPending, asset.id]);
										await onQueueDD(asset);
									}}
								>
									+ DD
								</button>
							{/if}
						</span>
					</div>
				{/each}

				{#if assets.length === 0 && !loading && !errorMessage}
					<div class="dg-empty" role="row">
						No instruments match the current filters.
					</div>
				{/if}
			</div>

			{#if isLoadingMore}
				<div class="dg-loading-more" style="top: {totalHeight}px;">
					LOADING PAGE {Math.ceil(assets.length / 200) + 1}...
				</div>
			{/if}

			{#if !hasMore && assets.length > 0 && !loading}
				<div class="dg-end-of-catalog" style="top: {totalHeight}px;">
					END OF CATALOG — {formatNumber(assets.length, 0)} instruments loaded
				</div>
			{/if}
		</div>
	</div>

	<div class="dg-footer">
		{#if errorMessage}
			<span class="dg-footer-err">{errorMessage}</span>
		{:else if loading}
			<span>Loading&hellip;</span>
		{:else if isLoadingMore}
			<span>Showing {formatNumber(assets.length, 0)} of {formatNumber(total, 0)} instruments — loading...</span>
		{:else if !hasMore && assets.length > 0}
			<span>Showing {formatNumber(assets.length, 0)} of {formatNumber(total, 0)} instruments — complete</span>
		{:else}
			<span>
				Showing {formatNumber(assets.length, 0)} of {formatNumber(total, 0)} instruments
			</span>
		{/if}
	</div>
</div>

<style>
	.dg-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
		font-size: 11px;
		color: var(--terminal-fg-primary);
	}

	/* ── Grid column template (shared by header + rows) ── */
	.dg-header,
	.dg-row {
		display: grid;
		grid-template-columns:
			72px                  /* ticker — fixed, always visible */
			minmax(100px, 1fr)    /* name — flex absorbs remaining space */
			90px                  /* type badges (MF/ETF + ELITE) */
			110px                 /* strategy — fixed */
			36px                  /* geo — 2-letter code */
			72px                  /* aum — right-aligned, compact format */
			60px                  /* 1y ret — right-aligned */
			60px                  /* 10y ret — right-aligned */
			48px                  /* er% — right-aligned */
			56px                  /* score — right-aligned numeral */
			72px;                 /* action — APPROVE/+DD button */
		column-gap: 2px;
		align-items: center;
	}

	/* ── Header ───────────────────────────────────────── */
	.dg-header {
		flex-shrink: 0;
		z-index: 2;
		background: var(--terminal-bg-panel-sunken);
		border-bottom: 1px solid var(--terminal-fg-disabled);
	}

	.dg-th {
		padding: 6px 6px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		white-space: nowrap;
		user-select: none;
	}

	/* ── Scroll container ─────────────────────────────── */
	.dg-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: auto;
		min-height: 0;
		outline: none;
	}

	.dg-spacer {
		position: relative;
		width: 100%;
	}

	.dg-rows {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
	}

	/* ── Rows ─────────────────────────────────────────── */
	.dg-row {
		cursor: pointer;
		transition: background 80ms ease;
	}
	.dg-row:hover {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 6%, transparent);
	}
	.dg-row.selected {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent);
	}
	.dg-row.highlighted {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 14%, transparent);
		outline: 1px solid color-mix(in srgb, var(--terminal-accent-cyan) 30%, transparent);
		outline-offset: -1px;
	}
	.dg-row.zebra {
		background: color-mix(in srgb, var(--terminal-fg-primary) 1.2%, transparent);
	}
	.dg-row.zebra:hover {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 6%, transparent);
	}
	.dg-row.zebra.selected {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent);
	}
	.dg-row.zebra.highlighted {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 14%, transparent);
	}

	/* ── Cells ────────────────────────────────────────── */
	.dg-td {
		padding: 5px 6px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.dg-right { text-align: right; }
	.dg-center { text-align: center; }

	.dg-ticker {
		font-weight: 700;
		color: var(--terminal-fg-primary);
	}

	.dg-name {
		color: var(--terminal-fg-secondary);
	}

	/* ── Type badges ────────────────────────────────── */
	.dg-type-badges {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.dg-type-badge {
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary, #5a6577);
		border: 1px solid rgba(255, 255, 255, 0.08);
		padding: 1px 4px;
		white-space: nowrap;
	}

	.dg-elite-inline {
		font-family: var(--terminal-font-mono);
		font-size: 8px;
		font-weight: 700;
		letter-spacing: 0.06em;
		color: var(--terminal-accent-amber, #f59e0b);
		border: 1px solid rgba(245, 158, 11, 0.35);
		padding: 1px 4px;
		white-space: nowrap;
	}

	.dg-strategy {
		color: var(--terminal-fg-secondary);
		font-size: 10px;
	}

	.dg-geo {
		color: var(--terminal-fg-tertiary);
		font-size: 10px;
	}

	.dg-num {
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}

	.pos { color: var(--terminal-status-success); }
	.neg { color: var(--terminal-status-error); }

	/* Score color coding */
	.score-high { color: var(--terminal-status-success); }
	.score-mid { color: var(--terminal-accent-amber); }
	.score-low { color: var(--terminal-status-error); }

	.dg-empty {
		padding: 32px;
		text-align: center;
		color: var(--terminal-fg-tertiary);
		font-size: 11px;
		font-style: italic;
	}

	/* ── Sparkline ───────────────────────────────────── */
	.dg-sparkline {
		display: block;
		width: 48px;
		height: 16px;
	}

	.dg-spark-empty {
		color: var(--terminal-fg-tertiary);
		font-size: 10px;
	}

	/* ── (old ticker badges removed — moved to TYPE column) ── */

	/* ── Action column ────────────────────────────────── */
	.dg-action-btn {
		background: transparent;
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.04em;
		padding: 2px 6px;
		cursor: pointer;
		transition: all 80ms ease;
		text-transform: uppercase;
	}
	.dg-action-approve {
		border: 1px solid color-mix(in srgb, var(--terminal-accent-amber) 35%, transparent);
		color: var(--terminal-accent-amber);
	}
	.dg-action-approve:hover {
		background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent);
		color: var(--terminal-accent-amber);
	}
	.dg-action-dd {
		border: 1px solid color-mix(in srgb, var(--terminal-accent-cyan) 25%, transparent);
		color: var(--terminal-accent-cyan);
	}
	.dg-action-dd:hover {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent);
		color: var(--terminal-accent-cyan);
	}
	.dg-action-label {
		font-family: var(--terminal-font-mono);
		font-size: 8px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.dg-action-approved {
		color: var(--terminal-status-success);
	}
	.dg-action-pending {
		color: var(--terminal-fg-tertiary);
	}

	/* ── Infinite scroll indicators ───────────────────── */
	.dg-loading-more {
		position: absolute;
		left: 0;
		right: 0;
		height: 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-family: var(--terminal-font-mono);
		font-size: 10px;
		letter-spacing: 0.06em;
		color: var(--terminal-fg-tertiary);
		animation: dg-pulse 1.2s ease-in-out infinite;
	}

	.dg-end-of-catalog {
		position: absolute;
		left: 0;
		right: 0;
		height: 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-family: var(--terminal-font-mono);
		font-size: 10px;
		letter-spacing: 0.06em;
		color: var(--terminal-fg-muted);
	}

	@keyframes dg-pulse {
		0%, 100% { opacity: 0.5; }
		50% { opacity: 1; }
	}

	/* ── Footer ───────────────────────────────────────── */
	.dg-footer {
		flex-shrink: 0;
		padding: 4px 10px;
		font-size: 10px;
		color: var(--terminal-fg-tertiary);
		border-top: 1px solid var(--terminal-fg-muted);
		background: var(--terminal-bg-panel-sunken);
	}
	.dg-footer-err {
		color: var(--terminal-status-error);
	}
</style>

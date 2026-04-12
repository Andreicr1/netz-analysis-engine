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
		expenseRatioPct: number | null;
		ret1y: number | null;
		ret10y: number | null;
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
	import { formatNumber } from "@investintell/ui";
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
		onSelect: (asset: ScreenerAsset) => void;
		onHighlight: (index: number) => void;
		onApprove: (asset: ScreenerAsset) => Promise<void>;
		onQueueDD: (asset: ScreenerAsset) => Promise<void>;
	}

	let {
		assets,
		total,
		loading,
		errorMessage,
		selectedId,
		highlightedIndex,
		onSelect,
		onHighlight,
		onApprove,
		onQueueDD,
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

	function handleScroll() {
		if (!scrollContainer) return;
		scrollTop = scrollContainer.scrollTop;
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

	// Reset scroll when assets change (new filter/sort)
	$effect(() => {
		// track assets reference
		void assets.length;
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
		ctx.strokeStyle = delta > 0 ? "#22c55e" : delta < 0 ? "#ef4444" : "#5a6577";
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

	// Fetch sparklines for visible rows (debounced 150ms)
	$effect(() => {
		const ids = visibleAssets
			.map((a) => a.instrumentId)
			.filter((id): id is string => id != null);

		// Deduplicate against already-cached IDs
		const uncachedIds = ids.filter((id) => !sparklineCache.has(id));
		const key = uncachedIds.sort().join(",");
		if (!key || key === lastFetchedIds) return;

		if (sparklineDebounce) clearTimeout(sparklineDebounce);
		sparklineDebounce = setTimeout(async () => {
			lastFetchedIds = key;
			try {
				const resp = await api.post<Record<string, SparklinePoint[]>>(
					"/screener/sparklines",
					{ instrument_ids: uncachedIds },
				);
				const next = new Map(sparklineCache);
				for (const [id, points] of Object.entries(resp)) {
					next.set(id, points.map((p) => p.nav_close));
				}
				sparklineCache = next;
			} catch {
				// Silently ignore — sparklines are non-critical
			}
		}, 150);

		return () => {
			if (sparklineDebounce) clearTimeout(sparklineDebounce);
		};
	});

	// Clear sparkline cache on filter change (assets reference changes)
	$effect(() => {
		void assets;
		sparklineCache = new Map();
		lastFetchedIds = "";
	});
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
		<span class="dg-th dg-col-spark">Trend</span>
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
		<!-- Spacer for total scroll height -->
		<div class="dg-spacer" style="height: {totalHeight}px;">
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
						<span class="dg-td dg-col-er dg-right dg-num">{fmtNum(asset.expenseRatioPct)}</span>
						<span class="dg-td dg-col-spark">
							{#if asset.instrumentId && sparklineCache.has(asset.instrumentId)}
								<canvas
									class="dg-sparkline"
									width={SPARKLINE_W}
									height={SPARKLINE_H}
									use:sparklineAction={asset.instrumentId}
								></canvas>
							{:else}
								<span class="dg-spark-empty">{"\u2014"}</span>
							{/if}
						</span>
						<span class="dg-td dg-col-action dg-center">
							{#if asset.inUniverse}
								<span class="dg-action-label dg-action-approved">IN UNIVERSE</span>
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
									{"\u2192"} UNIVERSE
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
		</div>
	</div>

	<div class="dg-footer">
		{#if errorMessage}
			<span class="dg-footer-err">{errorMessage}</span>
		{:else if loading}
			<span>Loading&hellip;</span>
		{:else}
			<span>
				Showing {assets.length} of {formatNumber(total, 0)} instruments
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
		background: #0b0f1a;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #c8d0dc;
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
			50px                  /* sparkline — 48px canvas + border */
			72px;                 /* action — APPROVE/+DD button */
		column-gap: 2px;
		align-items: center;
	}

	/* ── Header ───────────────────────────────────────── */
	.dg-header {
		flex-shrink: 0;
		z-index: 2;
		background: #0d1220;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
	}

	.dg-th {
		padding: 6px 6px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #5a6577;
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
		background: rgba(45, 126, 247, 0.06);
	}
	.dg-row.selected {
		background: rgba(45, 126, 247, 0.10);
	}
	.dg-row.highlighted {
		background: rgba(45, 126, 247, 0.14);
		outline: 1px solid rgba(45, 126, 247, 0.30);
		outline-offset: -1px;
	}
	.dg-row.zebra {
		background: rgba(255, 255, 255, 0.012);
	}
	.dg-row.zebra:hover {
		background: rgba(45, 126, 247, 0.06);
	}
	.dg-row.zebra.selected {
		background: rgba(45, 126, 247, 0.10);
	}
	.dg-row.zebra.highlighted {
		background: rgba(45, 126, 247, 0.14);
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
		color: #e2e8f0;
	}

	.dg-name {
		color: #9aa3b3;
	}

	/* ── Type badges ────────────────────────────────── */
	.dg-type-badges {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.dg-type-badge {
		font-family: "JetBrains Mono", monospace;
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
		font-family: "JetBrains Mono", monospace;
		font-size: 8px;
		font-weight: 700;
		letter-spacing: 0.06em;
		color: var(--terminal-accent-amber, #f59e0b);
		border: 1px solid rgba(245, 158, 11, 0.35);
		padding: 1px 4px;
		white-space: nowrap;
	}

	.dg-strategy {
		color: #8a94a6;
		font-size: 10px;
	}

	.dg-geo {
		color: #5a6577;
		font-size: 10px;
	}

	.dg-num {
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}

	.pos { color: #22c55e; }
	.neg { color: #ef4444; }

	.dg-empty {
		padding: 32px;
		text-align: center;
		color: #5a6577;
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
		color: #5a6577;
		font-size: 10px;
	}

	/* ── (old ticker badges removed — moved to TYPE column) ── */

	/* ── Action column ────────────────────────────────── */
	.dg-action-btn {
		background: transparent;
		font-family: "JetBrains Mono", monospace;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.04em;
		padding: 2px 6px;
		cursor: pointer;
		transition: all 80ms ease;
		text-transform: uppercase;
	}
	.dg-action-approve {
		border: 1px solid rgba(245, 158, 11, 0.35);
		color: #f59e0b;
	}
	.dg-action-approve:hover {
		background: rgba(245, 158, 11, 0.08);
		color: #fbbf24;
	}
	.dg-action-dd {
		border: 1px solid rgba(45, 126, 247, 0.25);
		color: #2d7ef7;
	}
	.dg-action-dd:hover {
		background: rgba(45, 126, 247, 0.08);
		color: #93bbfc;
	}
	.dg-action-label {
		font-family: "JetBrains Mono", monospace;
		font-size: 8px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.dg-action-approved {
		color: #22c55e;
	}
	.dg-action-pending {
		color: #5a6577;
	}

	/* ── Footer ───────────────────────────────────────── */
	.dg-footer {
		flex-shrink: 0;
		padding: 4px 10px;
		font-size: 10px;
		color: #5a6577;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		background: #0d1220;
	}
	.dg-footer-err {
		color: #ef4444;
	}
</style>

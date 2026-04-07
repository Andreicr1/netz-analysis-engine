/**
 * Portfolio Analytics Store — derived reactive state fusing live prices + positions.
 *
 * Reads from MarketDataStore (live ticks) and static holdings (SSR) to compute:
 *   - Real-time position value: weight * portfolio_nav (adjusted by price changes)
 *   - Intraday P&L ($ and %): (live_price - previous_close) / previous_close * position_value
 *   - Total Portfolio NAV: inception_nav * (1 + weighted sum of price changes)
 *   - Live Asset Allocation: group by asset_class
 *
 * Svelte 5 $derived is key — recomputation is automatic as prices tick in.
 * No localStorage. All state is in-memory.
 */

import type { MarketDataStore, HoldingSummary, PriceTick } from "./market-data.svelte";

// ── Types ───────────────────────────────────────────────────

export interface PositionAnalytics {
	instrument_id: string;
	ticker: string;
	name: string;
	asset_class: string;
	currency: string;
	weight: number;

	// Pricing — live or fallback to last known
	livePrice: number;
	previousClose: number;
	priceSource: "live" | "ssr";

	// Computed
	positionValue: number;
	intradayPnl: number;
	intradayPnlPct: number;
	allocationPct: number;
}

export interface AllocationBucket {
	assetClass: string;
	totalValue: number;
	pct: number;
	holdings: number;
}

export interface PortfolioAnalyticsStore {
	readonly positions: PositionAnalytics[];
	readonly totalNav: number;
	readonly totalPnl: number;
	readonly totalPnlPct: number;
	readonly allocation: AllocationBucket[];
	readonly gainers: PositionAnalytics[];
	readonly losers: PositionAnalytics[];
	readonly lastUpdated: string | null;
}

// ── Store Factory ───────────────────────────────────────────

/**
 * Create a portfolio analytics store. Requires a reference to the MarketDataStore
 * (which provides both holdings and live prices).
 *
 * All derived values recompute automatically as marketStore.priceMap or
 * marketStore.holdings change — Svelte 5 reactivity handles propagation.
 */
export function createPortfolioAnalytics(
	marketStore: MarketDataStore,
	inceptionNav: number = 1000,
): PortfolioAnalyticsStore {

	// ── Core derivations ────────────────────────────────────

	/**
	 * Fuse holdings with live prices. For each holding:
	 * - If a live price exists in priceMap, use it
	 * - Otherwise, fall back to the SSR price from holdings
	 */
	let positions = $derived.by((): PositionAnalytics[] => {
		const holdings = marketStore.holdings;
		const prices = marketStore.priceMap;

		if (holdings.length === 0) return [];

		// First pass: compute raw position values
		const raw: Array<{
			h: HoldingSummary;
			tick: PriceTick | undefined;
			livePrice: number;
			previousClose: number;
			priceSource: "live" | "ssr";
			changePct: number;
		}> = [];

		for (const h of holdings) {
			const tick = prices[h.ticker];
			const livePrice = tick?.price ?? h.price;
			// Previous close = price - change (from SSR or tick)
			const change = tick?.change ?? h.change;
			const previousClose = livePrice - change;
			const priceSource: "live" | "ssr" = tick ? "live" : "ssr";

			// Price change pct from previous close
			const changePct =
				previousClose > 0 ? ((livePrice - previousClose) / previousClose) : 0;

			raw.push({ h, tick, livePrice, previousClose, priceSource, changePct });
		}

		// Portfolio NAV = inception * (1 + weighted sum of changes)
		const weightedReturn = raw.reduce(
			(sum, r) => sum + r.h.weight * r.changePct, 0,
		);
		const navNow = inceptionNav * (1 + weightedReturn);

		// Second pass: compute position values
		return raw.map((r) => {
			const positionValue = r.h.weight * navNow;
			const intradayPnl = positionValue * r.changePct;

			return {
				instrument_id: r.h.instrument_id,
				ticker: r.h.ticker,
				name: r.h.name,
				asset_class: r.h.asset_class,
				currency: r.h.currency,
				weight: r.h.weight,
				livePrice: r.livePrice,
				previousClose: r.previousClose,
				priceSource: r.priceSource,
				positionValue,
				intradayPnl,
				intradayPnlPct: r.changePct * 100,
				allocationPct: navNow > 0 ? (positionValue / navNow) * 100 : 0,
			};
		});
	});

	let totalNav = $derived(
		positions.reduce((sum, p) => sum + p.positionValue, 0),
	);

	let totalPnl = $derived(
		positions.reduce((sum, p) => sum + p.intradayPnl, 0),
	);

	let totalPnlPct = $derived(
		totalNav > 0 && positions.length > 0
			? positions.reduce((sum, p) => sum + p.weight * (p.intradayPnlPct / 100), 0) * 100
			: 0,
	);

	/**
	 * Asset allocation — group positions by asset_class.
	 */
	let allocation = $derived.by((): AllocationBucket[] => {
		const buckets = new Map<string, { totalValue: number; count: number }>();

		for (const p of positions) {
			const cls = p.asset_class || "Other";
			const existing = buckets.get(cls);
			if (existing) {
				existing.totalValue += p.positionValue;
				existing.count++;
			} else {
				buckets.set(cls, { totalValue: p.positionValue, count: 1 });
			}
		}

		const nav = totalNav || 1;
		return Array.from(buckets.entries())
			.map(([assetClass, b]) => ({
				assetClass,
				totalValue: b.totalValue,
				pct: (b.totalValue / nav) * 100,
				holdings: b.count,
			}))
			.sort((a, b) => b.pct - a.pct);
	});

	let gainers = $derived(
		[...positions].filter((p) => p.intradayPnlPct > 0).sort((a, b) => b.intradayPnlPct - a.intradayPnlPct),
	);

	let losers = $derived(
		[...positions].filter((p) => p.intradayPnlPct < 0).sort((a, b) => a.intradayPnlPct - b.intradayPnlPct),
	);

	let lastUpdated = $derived(marketStore.asOf);

	return {
		get positions() { return positions; },
		get totalNav() { return totalNav; },
		get totalPnl() { return totalPnl; },
		get totalPnlPct() { return totalPnlPct; },
		get allocation() { return allocation; },
		get gainers() { return gainers; },
		get losers() { return losers; },
		get lastUpdated() { return lastUpdated; },
	};
}

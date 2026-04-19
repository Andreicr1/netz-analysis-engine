/**
 * FRED series → Tiingo proxy symbol map (plan §B.3).
 *
 * Only series where a liquid, continuously-quoted ETF proxy exists
 * are mapped. Everything else stays REST-only — the 5-min FRED poll
 * remains the authoritative source for the macro indicator.
 *
 * IMPORTANT — the proxy is NOT unit-equivalent to the FRED series:
 *  - VIXCLS (spot VIX index) ≈ VXX (S&P500 VIX Short-Term ETF). VXX
 *    has roll-yield decay; the sparkline number is NOT the VIX.
 *  - DTWEXBGS (Fed broad trade-weighted dollar index) ≠ UUP (USD vs
 *    6-currency basket ETF). Directionally correlated, absolutely
 *    different scale.
 *  - DGS10 (10-year Treasury yield, %) vs IEF (7-10yr Treasury ETF
 *    price, USD). Inversely correlated — an IEF price tick UP is a
 *    DGS10 yield tick DOWN.
 *
 * Therefore the consumer (SparklineWall) uses proxy data ONLY for a
 * "LIVE" badge + timestamp surface, never to replace the FRED value
 * or to append into the historical sparkline array. The underlying
 * macro number stays canonical; the proxy is a freshness signal.
 */

const SERIES_TO_SYMBOL: Record<string, string> = {
	VIXCLS: "VXX",
	DTWEXBGS: "UUP",
	DGS10: "IEF",
};

export function proxyFor(seriesId: string): string | null {
	return SERIES_TO_SYMBOL[seriesId] ?? null;
}

/**
 * Reverse lookup — which FRED series does a Tiingo symbol proxy?
 * Used by `SparklineWall` to route incoming WS ticks back to the
 * right indicator cell without re-scanning the full mapping.
 */
export function seriesForProxy(symbol: string): string | null {
	const upper = symbol.toUpperCase();
	for (const [series, proxy] of Object.entries(SERIES_TO_SYMBOL)) {
		if (proxy === upper) return series;
	}
	return null;
}

export const PROXY_SYMBOLS: readonly string[] = Object.values(SERIES_TO_SYMBOL);

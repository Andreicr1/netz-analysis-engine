/**
 * Risk Engine Client — fetches pre-computed risk timeseries from backend.
 *
 * Consumes GET /api/v1/risk/timeseries/{instrument_id} and formats data
 * into TradingView-compatible { time, value } arrays.
 *
 * All computation (drawdown, GARCH, regime) is done server-side
 * in TimescaleDB — zero math in the frontend.
 *
 * Primary key is instrument_id (UUID), consistent with the rest of the
 * wealth domain. Ticker is only used for display labels, never for
 * routing or lookups.
 */

import { createClientApiClient } from "$wealth/api/client";

export interface TVPoint {
	time: number; // UNIX seconds
	value: number;
}

export interface RegimeTVPoint extends TVPoint {
	regime: string;
}

export interface RiskTimeseries {
	instrumentId: string;
	ticker: string | null;
	drawdown: TVPoint[];
	/** Institutional label for GARCH-filtered volatility. Client key
	 * kept stable for chart callers; wire key is `conditional_volatility`. */
	volatilityGarch: TVPoint[];
	regimeProb: RegimeTVPoint[];
}

interface RawPoint {
	time: string; // ISO-8601 date
	value: number;
}

interface RawRegimePoint extends RawPoint {
	regime: string; // sanitised label: Expansion / Cautious / Stress
}

interface RawResponse {
	instrument_id: string;
	ticker: string | null;
	from_date: string;
	to_date: string;
	drawdown: RawPoint[];
	// Backend emits `conditional_volatility` as of Phase 2 Session C
	// commit 2 — the previous `volatility_garch` key is gone.
	conditional_volatility: RawPoint[];
	regime_prob: RawRegimePoint[];
}

/** Convert ISO-8601 date string to UNIX seconds (midnight UTC). */
function isoToUnix(iso: string): number {
	return Math.floor(new Date(iso + "T00:00:00Z").getTime() / 1000);
}

function mapPoints(raw: RawPoint[]): TVPoint[] {
	return raw.map((p) => ({ time: isoToUnix(p.time), value: p.value }));
}

function mapRegimePoints(raw: RawRegimePoint[]): RegimeTVPoint[] {
	return raw.map((p) => ({
		time: isoToUnix(p.time),
		value: p.value,
		regime: p.regime,
	}));
}

/**
 * Fetch risk timeseries for an instrument from the backend.
 *
 * Uses the shared authenticated client so the request hits the real
 * API base URL (VITE_API_BASE_URL) with the Clerk token attached.
 *
 * @param instrumentId - UUID of the instrument in instruments_universe
 * @param getToken     - Clerk token provider from the page context
 * @param opts         - Optional ISO date range
 * @returns Formatted series ready for TradingView injection
 */
export async function fetchRiskTimeseries(
	instrumentId: string,
	getToken: () => Promise<string>,
	opts?: {
		from?: string; // ISO date
		to?: string;
	},
): Promise<RiskTimeseries> {
	const api = createClientApiClient(getToken);

	const params = new URLSearchParams();
	if (opts?.from) params.set("from", opts.from);
	if (opts?.to) params.set("to", opts.to);
	const qs = params.toString();

	const path = `/risk/timeseries/${encodeURIComponent(instrumentId)}${qs ? `?${qs}` : ""}`;
	const data = await api.get<RawResponse>(path);

	return {
		instrumentId: data.instrument_id,
		ticker: data.ticker,
		drawdown: mapPoints(data.drawdown),
		volatilityGarch: mapPoints(data.conditional_volatility),
		regimeProb: mapRegimePoints(data.regime_prob),
	};
}

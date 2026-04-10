/**
 * Risk Engine Client — fetches pre-computed risk timeseries from backend.
 *
 * Consumes GET /api/v1/risk/timeseries/{ticker} and formats data
 * into TradingView-compatible { time, value } arrays.
 *
 * All computation (drawdown, GARCH, regime) is done server-side
 * in TimescaleDB — zero math in the frontend.
 */

export interface TVPoint {
	time: number; // UNIX seconds
	value: number;
}

export interface RegimeTVPoint extends TVPoint {
	regime: string;
}

export interface RiskTimeseries {
	ticker: string;
	instrumentId: string;
	drawdown: TVPoint[];
	volatilityGarch: TVPoint[];
	regimeProb: RegimeTVPoint[];
}

interface RawPoint {
	time: string; // ISO-8601 date
	value: number;
}

interface RawRegimePoint extends RawPoint {
	regime: string;
}

interface RawResponse {
	ticker: string;
	instrument_id: string;
	from_date: string;
	to_date: string;
	drawdown: RawPoint[];
	volatility_garch: RawPoint[];
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
 * Fetch risk timeseries for a ticker from the backend.
 *
 * @param ticker - Fund ticker (e.g. "VFIAX")
 * @param opts - Optional date range and auth token
 * @returns Formatted series ready for TradingView injection
 */
export async function fetchRiskTimeseries(
	ticker: string,
	opts?: {
		from?: string; // ISO date
		to?: string;
		token?: string;
	},
): Promise<RiskTimeseries> {
	const params = new URLSearchParams();
	if (opts?.from) params.set("from", opts.from);
	if (opts?.to) params.set("to", opts.to);

	const qs = params.toString();
	const url = `/api/v1/risk/timeseries/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ""}`;

	const headers: Record<string, string> = {
		Accept: "application/json",
	};
	if (opts?.token) {
		headers.Authorization = `Bearer ${opts.token}`;
	}

	const resp = await fetch(url, { headers });
	if (!resp.ok) {
		throw new Error(`Risk timeseries fetch failed: ${resp.status} ${resp.statusText}`);
	}

	const data: RawResponse = await resp.json();

	return {
		ticker: data.ticker,
		instrumentId: data.instrument_id,
		drawdown: mapPoints(data.drawdown),
		volatilityGarch: mapPoints(data.volatility_garch),
		regimeProb: mapRegimePoints(data.regime_prob),
	};
}

/**
 * Analysis API client.
 *
 * Mirrors the auth pattern of `$lib/discovery/api.ts` — callers pass a
 * `getToken` callback obtained via
 * `getContext<() => Promise<string>>("netz:getToken")`. Each function builds
 * its own `Authorization: Bearer ...` header so components stay decoupled
 * from how the JWT is resolved at the layout level.
 */

const BASE = "/api/wealth/discovery";

export type GetToken = () => Promise<string>;

async function authHeaders(getToken: GetToken): Promise<HeadersInit> {
	const token = await getToken();
	return { Authorization: `Bearer ${token}` };
}

export type AnalysisWindow = "1y" | "3y" | "5y" | "max";

/**
 * GET /funds/{id}/analysis/returns-risk?window={window}
 *
 * Returns: `{ window, nav_series, monthly_returns, rolling_metrics,
 * return_distribution, risk_metrics, disclosure, fund }`. Shape is validated
 * by the caller (ReturnsRiskView) to keep this module framework-free.
 */
export async function fetchReturnsRisk(
	getToken: GetToken,
	fundId: string,
	window: AnalysisWindow,
	signal: AbortSignal,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/analysis/returns-risk?window=${window}`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`returns-risk fetch: ${res.status}`);
	return res.json();
}

/**
 * GET /funds/{id}/analysis/holdings/top
 *
 * Returns: `{ top_holdings, sector_breakdown, as_of, disclosure }`. Only
 * N-PORT universes (registered, ETF, BDC) expose holdings; private funds
 * return `disclosure.has_holdings === false`.
 */
export async function fetchHoldingsTop(
	getToken: GetToken,
	fundId: string,
	signal: AbortSignal,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/analysis/holdings/top`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`holdings/top fetch: ${res.status}`);
	return res.json();
}

/**
 * GET /funds/{id}/analysis/holdings/style-drift?quarters=N
 *
 * Returns: `{ snapshots: [{ quarter, sectors: [{name, weight}] }] }`. Used
 * by StyleDriftFlow to render a stacked area chart across the last N filings.
 */
export async function fetchStyleDrift(
	getToken: GetToken,
	fundId: string,
	quarters: number,
	signal: AbortSignal,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/analysis/holdings/style-drift?quarters=${quarters}`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`style-drift fetch: ${res.status}`);
	return res.json();
}

/**
 * GET /holdings/{cusip}/reverse-lookup?limit=N
 *
 * Returns: `{ nodes, edges, target_cusip }`. Aggregates all 13F and N-PORT
 * filers reporting a position in the given CUSIP so HoldingsNetworkChart can
 * draw the "who holds this" network.
 */
export async function fetchReverseLookup(
	getToken: GetToken,
	cusip: string,
	signal: AbortSignal,
	limit = 30,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/holdings/${encodeURIComponent(cusip)}/reverse-lookup?limit=${limit}`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`reverse-lookup fetch: ${res.status}`);
	return res.json();
}

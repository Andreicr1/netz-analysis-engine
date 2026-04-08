/**
 * Analysis API client.
 *
 * Mirrors the auth pattern of `$lib/discovery/api.ts` — callers pass a
 * `getToken` callback obtained via
 * `getContext<() => Promise<string>>("netz:getToken")`. Each function builds
 * its own `Authorization: Bearer ...` header so components stay decoupled
 * from how the JWT is resolved at the layout level.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const BASE = `${API_BASE}/wealth/discovery`;

export type GetToken = () => Promise<string>;

async function authHeaders(getToken: GetToken): Promise<HeadersInit> {
	const token = await getToken();
	return { Authorization: `Bearer ${token}` };
}

export type AnalysisWindow = "1y" | "3y" | "5y" | "max";

/**
 * Flat risk metrics payload emitted by `/funds/{id}/analysis/returns-risk`.
 *
 * Keys mirror the `fund_risk_metrics` columns the backend agent locked as
 * the stable contract for the Discovery Analysis view (Branch #1 of the
 * 2026-04-08 fix sprint). All numeric fields are nullable because the
 * backend returns `None` when the underlying computation has no data
 * (e.g. private funds with no public NAV series).
 */
export interface RiskMetricsPayload {
	sharpe_1y: number | null;
	volatility_1y: number | null;
	volatility_garch: number | null;
	cvar_95_12m: number | null;
	cvar_95_conditional: number | null;
	max_drawdown_1y: number | null;
	return_1y: number | null;
	manager_score: number | null;
	blended_momentum_score: number | null;
	peer_sharpe_pctl: number | null;
	peer_sortino_pctl: number | null;
	peer_return_pctl: number | null;
	peer_drawdown_pctl: number | null;
	peer_count: number | null;
	peer_strategy: string | null;
	calc_date: string | null;
}

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
 * GET /funds/{id}/analysis/peers?limit=N
 *
 * Returns: `{ peers: [...], subject: {...} | null }`. Each peer has
 * `external_id, name, ticker, strategy_label, aum_usd, expense_ratio_pct,
 * volatility_1y, sharpe_1y, max_drawdown_1y, cvar_95, is_subject`. The
 * subject fund is also included in the `peers` array (with `is_subject:
 * true`) so charts can highlight it inline.
 */
export async function fetchPeerComparison(
	getToken: GetToken,
	fundId: string,
	signal: AbortSignal,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/analysis/peers`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`peers fetch: ${res.status}`);
	return res.json();
}

/**
 * GET /funds/{id}/analysis/institutional-reveal?categories=...
 *
 * Returns: `{ institutions, overlap_matrix, holdings }`. `institutions` may
 * be empty if the curated CIK backfill has not run yet — `holdings` still
 * populates so the heatmap can show holdings as labels with no overlap data.
 */
export async function fetchInstitutionalReveal(
	getToken: GetToken,
	fundId: string,
	signal: AbortSignal,
): Promise<unknown> {
	const res = await fetch(
		`${BASE}/funds/${encodeURIComponent(fundId)}/analysis/institutional-reveal`,
		{
			headers: await authHeaders(getToken),
			signal,
		},
	);
	if (!res.ok) throw new Error(`institutional-reveal fetch: ${res.status}`);
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

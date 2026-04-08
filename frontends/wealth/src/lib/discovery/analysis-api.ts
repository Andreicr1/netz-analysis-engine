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

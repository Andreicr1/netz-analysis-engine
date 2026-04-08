/**
 * Analysis page server load.
 *
 * Fetches the fact-sheet header (fund name, ticker, strategy) so the first
 * paint shows a fully labeled header while the group-specific view queries
 * its own dataset client-side. Uses the RouteData<T>-style shape
 * (status: 'ok' | 'error') — never `throw error()` — so the route renders
 * a panel error state without tripping the global error boundary.
 */
import type { PageServerLoad } from "./$types";

type Group = "returns-risk" | "holdings" | "peer";
type Window = "1y" | "3y" | "5y" | "max";

const VALID_GROUPS: readonly Group[] = ["returns-risk", "holdings", "peer"];
const VALID_WINDOWS: readonly Window[] = ["1y", "3y", "5y", "max"];

function parseGroup(raw: string | null): Group {
	return (VALID_GROUPS as readonly string[]).includes(raw ?? "")
		? (raw as Group)
		: "returns-risk";
}

function parseWindow(raw: string | null): Window {
	return (VALID_WINDOWS as readonly string[]).includes(raw ?? "")
		? (raw as Window)
		: "3y";
}

export const load: PageServerLoad = async ({ fetch, params, url }) => {
	const fsRes = await fetch(
		`/api/wealth/discovery/funds/${encodeURIComponent(params.external_id)}/fact-sheet`,
	);
	if (!fsRes.ok) {
		return {
			status: "error" as const,
			error: `fact-sheet load: ${fsRes.status}`,
			fundId: params.external_id,
			initialGroup: parseGroup(url.searchParams.get("group")),
			initialWindow: parseWindow(url.searchParams.get("window")),
		};
	}
	const header = await fsRes.json();
	return {
		status: "ok" as const,
		fundId: params.external_id,
		header,
		initialGroup: parseGroup(url.searchParams.get("group")),
		initialWindow: parseWindow(url.searchParams.get("window")),
	};
};

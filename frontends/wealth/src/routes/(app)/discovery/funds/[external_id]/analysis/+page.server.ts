/**
 * Analysis page server load.
 *
 * Kept minimal: only parses URL params and passes the external_id.
 * The fact-sheet header + group-specific data are fetched client-side
 * via `fetchFundFactSheet(getToken, ...)` because Clerk auth tokens
 * are only available in the browser context.
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

export const load: PageServerLoad = async ({ params, url }) => {
	return {
		fundId: params.external_id,
		initialGroup: parseGroup(url.searchParams.get("group")),
		initialWindow: parseWindow(url.searchParams.get("window")),
	};
};

/**
 * Screener fund Risk Analysis — server load.
 *
 * Mirrors the shape of the discovery analysis loader: parses the
 * ``group`` and ``window`` query params, hands them to the client as
 * `initialGroup` / `initialWindow`. The fund header and group-specific
 * payloads are fetched client-side via `fetchFundFactSheet` and the
 * `$lib/discovery/analysis-api` helpers because Clerk JWTs are only
 * available in the browser context.
 *
 * Route param `id` is the canonical fund external_id — the same value
 * carried by the discovery route's ``external_id`` segment and the one
 * the backend's ``/wealth/discovery/funds/{id}/analysis/*`` endpoints
 * expect. Branch #1 fixed the resolver to walk class_id → series_id →
 * CIK, so every fund that renders in the Screener grid resolves here.
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
		fundId: params.id,
		initialGroup: parseGroup(url.searchParams.get("group")),
		initialWindow: parseWindow(url.searchParams.get("window")),
	};
};

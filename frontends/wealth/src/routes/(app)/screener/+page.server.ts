/** Unified Screener SSR — Manager-first with 3-level drill-down.
 *
 * Level 1: Fund Managers (from /manager-screener/)
 * Level 2: Funds by Manager (client-side, via /screener/catalog?manager_id=)
 * Level 3: Share Classes (client-side, via /screener/funds/{id}/classes)
 *
 * Screening tab remains for on-demand screening of imported instruments.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreenerPage } from "$lib/types/manager-screener";
import { EMPTY_SCREENER } from "$lib/types/manager-screener";
import type { ScreeningRun, ScreeningResult } from "$lib/types/screening";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const page = url.searchParams.get("page") ?? "1";
	const pageSize = url.searchParams.get("page_size") ?? "25";
	const textSearch = url.searchParams.get("q") ?? "";
	const sortBy = url.searchParams.get("sort_by") ?? "aum_total";
	const sortDir = url.searchParams.get("sort_dir") ?? "desc";
	const aumMin = url.searchParams.get("aum_min");

	const managerParams: Record<string, string> = {
		page,
		page_size: pageSize,
		sort_by: sortBy,
		sort_dir: sortDir,
	};
	if (textSearch) managerParams.text_search = textSearch;
	if (aumMin) managerParams.aum_min = aumMin;

	const [managers, screeningRuns, screeningResults] = await Promise.all([
		api.get<ScreenerPage>("/manager-screener/", managerParams).catch(() => EMPTY_SCREENER),
		api.get<ScreeningRun[]>("/screener/runs", { limit: "10" }).catch(() => [] as ScreeningRun[]),
		api.get<ScreeningResult[]>("/screener/results", { is_current: "true", limit: "100" }).catch(() => [] as ScreeningResult[]),
	]);

	return {
		tab: url.searchParams.get("tab") ?? "catalog",
		managers,
		screeningRuns,
		screeningResults,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

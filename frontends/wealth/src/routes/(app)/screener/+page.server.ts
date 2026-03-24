/** Unified Screener SSR — dual mode: instrument search + manager screener. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreeningResult, ScreeningRun, InstrumentSearchPage, ScreenerFacets } from "$lib/types/screening";
import type { ScreenerPage } from "$lib/types/manager-screener";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const mode = url.searchParams.get("mode") ?? "instruments";

	// Search params for instrument mode
	const searchParams: Record<string, string> = {};
	for (const key of ["q", "instrument_type", "asset_class", "geography", "domicile", "currency", "strategy", "source", "approval_status", "block_id", "aum_min", "aum_max"]) {
		const val = url.searchParams.get(key);
		if (val) searchParams[key] = val;
	}
	searchParams.page = url.searchParams.get("page") ?? "1";
	searchParams.page_size = url.searchParams.get("page_size") ?? "50";

	// Manager params
	const mgrParams = new URLSearchParams();
	for (const [key, value] of url.searchParams.entries()) {
		mgrParams.append(key, value);
	}
	if (!mgrParams.has("page")) mgrParams.set("page", "1");
	if (!mgrParams.has("page_size")) mgrParams.set("page_size", "25");

	const [facets, searchResults, screener, results, runs] = await Promise.all([
		api.get<ScreenerFacets>("/screener/facets", searchParams).catch(() => null),
		api.get<InstrumentSearchPage>("/screener/search", searchParams).catch(() => ({ items: [], total: 0, page: 1, page_size: 50, has_next: false }) as InstrumentSearchPage),
		api.get<ScreenerPage>(`/manager-screener/?${mgrParams.toString()}`).catch(() => null),
		api.get<ScreeningResult[]>("/screener/results", { limit: "500" }).catch(() => [] as ScreeningResult[]),
		api.get<ScreeningRun[]>("/screener/runs", { limit: "1" }).catch(() => [] as ScreeningRun[]),
	]);

	return {
		mode,
		facets,
		searchResults,
		screener,
		results,
		lastRun: runs[0] ?? null,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

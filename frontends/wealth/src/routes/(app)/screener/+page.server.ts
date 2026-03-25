/** Unified Screener SSR — instrument search with tab-based instrument_type filter. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreeningResult, ScreeningRun, InstrumentSearchPage, ScreenerFacets } from "$lib/types/screening";

const TAB_TO_INSTRUMENT_TYPE: Record<string, string> = {
	fund: "fund",
	equity: "equity",
	bond: "bond",
	etf: "etf",
};

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Map tab param to instrument_type for backend
	const tab = url.searchParams.get("tab") ?? "fund";
	const instrumentType = TAB_TO_INSTRUMENT_TYPE[tab] ?? "fund";

	// Search params for instrument mode
	const searchParams: Record<string, string> = {};
	for (const key of ["q", "asset_class", "geography", "domicile", "currency", "strategy", "source", "approval_status", "block_id", "aum_min", "aum_max", "fund_type", "manager", "sector", "exchange", "market_cap_min", "pe_max", "div_yield_min", "bond_asset_class", "maturity_range", "ytm_min", "fund_family", "expense_ratio_max"]) {
		const val = url.searchParams.get(key);
		if (val) searchParams[key] = val;
	}
	searchParams.instrument_type = instrumentType;
	searchParams.page = url.searchParams.get("page") ?? "1";
	searchParams.page_size = url.searchParams.get("page_size") ?? "50";

	const [facets, searchResults, results, runs] = await Promise.all([
		api.get<ScreenerFacets>("/screener/facets", searchParams).catch(() => null),
		api.get<InstrumentSearchPage>("/screener/search", searchParams).catch(() => ({ items: [], total: 0, page: 1, page_size: 50, has_next: false }) as InstrumentSearchPage),
		api.get<ScreeningResult[]>("/screener/results", { limit: "500" }).catch(() => [] as ScreeningResult[]),
		api.get<ScreeningRun[]>("/screener/runs", { limit: "1" }).catch(() => [] as ScreeningRun[]),
	]);

	return {
		facets,
		searchResults,
		results,
		lastRun: runs[0] ?? null,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

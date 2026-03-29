/** Unified Screener SSR — all tabs route to GLOBAL endpoints (no RLS).
 *
 * Tab "catalog" (default): GET /screener/catalog + /screener/catalog/facets (3-universe funds)
 * Tab "equities":           GET /screener/securities + /screener/securities/facets (global SEC)
 * Tab "managers":           GET /sec/managers/search (global SEC ADV)
 *
 * ETF tab removed — ETFs are in Fund Catalog (registered_us + fund_type=etf).
 * Bond tab removed — no global bond master table; bonds visible via N-PORT holdings.
 *
 * ARCHITECTURAL RULE: instruments_universe (RLS) is the DESTINATION, not the source.
 * Screener is DISCOVERY → DD Report → Approval → Import to Universe.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UnifiedCatalogPage, CatalogFacets, SecurityPage, SecurityFacets } from "$lib/types/catalog";
import type { SecManagerSearchPage, SecSicCodeItem } from "$lib/types/sec-analysis";
import { EMPTY_CATALOG_PAGE, EMPTY_FACETS, EMPTY_SECURITY_PAGE, EMPTY_SECURITY_FACETS } from "$lib/types/catalog";
import { EMPTY_SEARCH_PAGE as EMPTY_MANAGER_PAGE } from "$lib/types/sec-analysis";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const tab = url.searchParams.get("tab") ?? "catalog";
	const page = url.searchParams.get("page") ?? "1";
	const pageSize = url.searchParams.get("page_size") ?? "50";

	if (tab === "catalog") {
		const catalogParams: Record<string, string> = { page, page_size: pageSize };
		const q = url.searchParams.get("q");
		if (q) catalogParams.q = q;
		// Category-based universe filter (7 categories → backend fund_universe)
		const category = url.searchParams.get("category");
		if (category) catalogParams.fund_universe = category;
		const fundTypes = url.searchParams.get("fund_type");
		if (fundTypes) catalogParams.fund_type = fundTypes;
		const strategyLabel = url.searchParams.get("strategy_label");
		if (strategyLabel) catalogParams.strategy_label = strategyLabel;
		const domiciles = url.searchParams.getAll("domicile");
		if (domiciles.length) catalogParams.domicile = domiciles.join(",");
		const aumMin = url.searchParams.get("aum_min");
		if (aumMin) catalogParams.aum_min = aumMin;
		const sort = url.searchParams.get("sort");
		if (sort) catalogParams.sort = sort;
		const maxER = url.searchParams.get("max_expense_ratio");
		if (maxER) catalogParams.max_expense_ratio = maxER;
		const minReturn1y = url.searchParams.get("min_return_1y");
		if (minReturn1y) catalogParams.min_return_1y = minReturn1y;
		const minReturn10y = url.searchParams.get("min_return_10y");
		if (minReturn10y) catalogParams.min_return_10y = minReturn10y;

		const [catalog, facets] = await Promise.all([
			api.get<UnifiedCatalogPage>("/screener/catalog", catalogParams).catch(() => EMPTY_CATALOG_PAGE),
			api.get<CatalogFacets>("/screener/catalog/facets", catalogParams).catch(() => EMPTY_FACETS),
		]);

		return { tab, catalog, catalogFacets: facets, currentParams: Object.fromEntries(url.searchParams.entries()) };
	}

	if (tab === "equities") {
		// ── GLOBAL equities from sec_cusip_ticker_map (no RLS) ──
		const secParams: Record<string, string> = { page, page_size: pageSize };
		const q = url.searchParams.get("q");
		if (q) secParams.q = q;
		const secType = url.searchParams.get("security_type");
		if (secType) secParams.security_type = secType;
		const exchange = url.searchParams.get("exchange");
		if (exchange) secParams.exchange = exchange;
		const sort = url.searchParams.get("sort");
		if (sort) secParams.sort = sort;

		const [securities, secFacets] = await Promise.all([
			api.get<SecurityPage>("/screener/securities", secParams).catch(() => EMPTY_SECURITY_PAGE),
			api.get<SecurityFacets>("/screener/securities/facets", { q: q ?? "" }).catch(() => EMPTY_SECURITY_FACETS),
		]);

		return { tab, securities, securityFacets: secFacets, currentParams: Object.fromEntries(url.searchParams.entries()) };
	}

	if (tab === "managers") {
		const params: Record<string, string> = { page, page_size: "25" };
		for (const key of ["q", "entity_type", "state", "has_13f", "aum_min", "fund_type"]) {
			const val = url.searchParams.get(key);
			if (val) params[key] = val;
		}

		const [searchResults, sicCodes] = await Promise.all([
			api.get<SecManagerSearchPage>("/sec/managers/search", params).catch(() => EMPTY_MANAGER_PAGE),
			api.get<SecSicCodeItem[]>("/sec/managers/sic-codes").catch(() => [] as SecSicCodeItem[]),
		]);

		return { tab, managerResults: searchResults, sicCodes, currentParams: Object.fromEntries(url.searchParams.entries()) };
	}

	// Fallback: redirect unknown tabs to catalog
	return { tab: "catalog", currentParams: Object.fromEntries(url.searchParams.entries()) };
};

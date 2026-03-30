/** Unified Screener SSR — Fund Catalog with server-side pagination.
 *
 * GET /screener/catalog + /screener/catalog/facets (3-universe funds)
 *
 * ARCHITECTURAL RULE: instruments_universe (RLS) is the DESTINATION, not the source.
 * Screener is DISCOVERY → DD Report → Approval → Import to Universe.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UnifiedCatalogPage, CatalogFacets } from "$lib/types/catalog";
import { EMPTY_CATALOG_PAGE, EMPTY_FACETS } from "$lib/types/catalog";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const page = url.searchParams.get("page") ?? "1";
	const pageSize = url.searchParams.get("page_size") ?? "50";

	const catalogParams: Record<string, string> = { page, page_size: pageSize };
	const q = url.searchParams.get("q");
	if (q) catalogParams.q = q;
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

	return {
		tab: "catalog",
		catalog,
		catalogFacets: facets,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

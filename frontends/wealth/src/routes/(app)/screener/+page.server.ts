/** Screener Level 1 — Manager Catalog SSR load.
 *
 * Fetches from GET /screener/catalog/managers (grouped by manager_id).
 * Default sort: AUM descending for institutional relevance.
 * Falls back to empty page on error to avoid blocking navigation.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ManagerCatalogPage } from "$lib/types/catalog";
import { EMPTY_MANAGER_CATALOG_PAGE } from "$lib/types/catalog";

export const load: PageServerLoad = async ({ url, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const q = url.searchParams.get("q") ?? "";
	const page = parseInt(url.searchParams.get("page") ?? "1", 10);
	const pageSize = 50;

	const aum_min = url.searchParams.get("aum_min");

	const sort = url.searchParams.get("sort") ?? "aum_desc";

	try {
		const params: Record<string, string> = {
			page: String(page),
			page_size: String(pageSize),
			sort: sort,
		};
		if (q) params.q = q;
		if (aum_min) params.aum_min = aum_min;

		const catalog = await api.get<ManagerCatalogPage>("/screener/catalog/managers", params);
		return { catalog, q, aum_min, page, sort };
	} catch {
		return { catalog: EMPTY_MANAGER_CATALOG_PAGE, q, aum_min, page, sort };
	}
};

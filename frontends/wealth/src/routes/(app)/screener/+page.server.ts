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

	const tab = url.searchParams.get("tab") ?? "screening";
	const q = url.searchParams.get("q") ?? "";
	const page = parseInt(url.searchParams.get("page") ?? "1", 10);
	const pageSize = 50;

	// Only fetch catalog for the "screening" tab
	if (tab !== "screening") {
		return { tab, catalog: EMPTY_MANAGER_CATALOG_PAGE, q, page: 1 };
	}

	try {
		const params: Record<string, string> = {
			page: String(page),
			page_size: String(pageSize),
			has_aum: "true",
			sort: "aum_desc",
		};
		if (q) params.q = q;

		const catalog = await api.get<ManagerCatalogPage>("/screener/catalog/managers", params);
		return { tab, catalog, q, page };
	} catch {
		return { tab, catalog: EMPTY_MANAGER_CATALOG_PAGE, q, page };
	}
};

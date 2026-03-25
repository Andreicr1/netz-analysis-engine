/** US Fund Analysis — SSR: load initial manager search results + SIC codes. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type {
	SecManagerSearchPage,
	SecSicCodeItem,
} from "$lib/types/sec-analysis";
import { EMPTY_SEARCH_PAGE } from "$lib/types/sec-analysis";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const q = url.searchParams.get("q") ?? "";
	const entity_type = url.searchParams.get("entity_type") ?? "";
	const state = url.searchParams.get("state") ?? "";
	const has_cik = url.searchParams.get("has_cik") ?? "";
	const aum_min = url.searchParams.get("aum_min") ?? "";
	const filed_within_days = url.searchParams.get("filed_within_days") ?? "";
	const sic = url.searchParams.get("sic") ?? "";
	const has_disclosures = url.searchParams.get("has_disclosures") ?? "";
	const page = url.searchParams.get("page") ?? "1";

	const params: Record<string, string> = { page, page_size: "25" };
	if (q) params.q = q;
	if (entity_type) params.entity_type = entity_type;
	if (state) params.state = state;
	if (has_cik) params.has_cik = has_cik;
	if (aum_min) params.aum_min = aum_min;
	if (filed_within_days) params.filed_within_days = filed_within_days;
	if (sic) params.sic = sic;
	if (has_disclosures) params.has_disclosures = has_disclosures;

	const [searchResults, sicCodes] = await Promise.all([
		api
			.get<SecManagerSearchPage>("/sec/managers/search", params)
			.catch(() => EMPTY_SEARCH_PAGE),
		api
			.get<SecSicCodeItem[]>("/sec/managers/sic-codes")
			.catch(() => [] as SecSicCodeItem[]),
	]);

	return {
		searchResults,
		sicCodes,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

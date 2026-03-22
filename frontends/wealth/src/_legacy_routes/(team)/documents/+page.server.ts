/** Wealth documents list — loads paginated documents. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const params: Record<string, string> = { limit: "100" };
	const portfolio_id = url.searchParams.get("portfolio_id");
	const domain = url.searchParams.get("domain");
	if (portfolio_id) params.portfolio_id = portfolio_id;
	if (domain) params.domain = domain;

	const [documents] = await Promise.allSettled([
		api.get("/wealth/documents", params),
	]);

	return {
		documents: documents.status === "fulfilled" ? documents.value : { items: [], limit: 100, offset: 0 },
	};
};

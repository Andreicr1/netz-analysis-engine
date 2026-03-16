/** Prompt list page — loads templates for all verticals. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [credit, wealth] = await Promise.allSettled([
		api.get<unknown[]>("/admin/prompts/private_credit"),
		api.get<unknown[]>("/admin/prompts/liquid_funds"),
	]);

	return {
		creditPrompts: credit.status === "fulfilled" ? credit.value : [],
		wealthPrompts: wealth.status === "fulfilled" ? wealth.value : [],
	};
};

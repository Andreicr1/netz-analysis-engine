/** Config list page — loads config entries for all verticals. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [credit, wealth] = await Promise.allSettled([
		api.get<unknown[]>("/admin/configs", { vertical: "private_credit" }),
		api.get<unknown[]>("/admin/configs", { vertical: "liquid_funds" }),
	]);

	return {
		creditConfigs: credit.status === "fulfilled" ? credit.value : [],
		wealthConfigs: wealth.status === "fulfilled" ? wealth.value : [],
	};
};

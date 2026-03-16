/** Tenant list page — loads all tenants. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [tenants] = await Promise.allSettled([
		api.get<unknown[]>("/admin/tenants"),
	]);

	return {
		tenants: tenants.status === "fulfilled" ? tenants.value : [],
	};
};

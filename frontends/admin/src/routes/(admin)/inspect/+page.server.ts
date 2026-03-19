/** Inspect page — loads tenant list for the selector. Inspection data fetched client-side. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

type TenantListResponse = {
	tenants: Array<{ organization_id: string; org_name: string }>;
	total: number;
};

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);

	const [tenantsResult] = await Promise.allSettled([
		api.get<TenantListResponse>("/admin/tenants", { limit: 200 }),
	]);

	return {
		tenants:
			tenantsResult.status === "fulfilled"
				? tenantsResult.value.tenants
				: [],
	};
};

/** Tenant detail page — loads tenant configs, assets, usage. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { orgId } = params;

	const [detail, assets] = await Promise.allSettled([
		api.get(`/admin/tenants/${orgId}`),
		api.get(`/admin/tenants/${orgId}/assets`),
	]);

	return {
		orgId,
		tenant: detail.status === "fulfilled" ? detail.value : null,
		assets: assets.status === "fulfilled" ? assets.value : [],
	};
};

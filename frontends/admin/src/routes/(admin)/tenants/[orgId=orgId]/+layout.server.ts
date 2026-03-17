import type { LayoutServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: LayoutServerLoad = async ({ locals, params }) => {
	const api = createServerApiClient(locals.token);
	let tenant = null;
	try {
		tenant = await api.get(`/admin/tenants/${params.orgId}`);
	} catch {
		/* fallback — API may not exist yet */
	}
	return { tenant, orgId: params.orgId };
};

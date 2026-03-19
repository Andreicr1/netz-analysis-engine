import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

type TenantListItem = {
	organization_id: string;
	org_name: string;
	org_slug: string;
	vertical: string;
	config_count: number;
	asset_count: number;
};

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);
	let tenants: TenantListItem[] = [];
	try {
		tenants = await api.get("/admin/tenants/");
	} catch {
		/* fallback — API may not exist yet */
	}
	return { tenants };
};

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);
	let tenants: Record<string, unknown>[] = [];
	try {
		tenants = await api.get("/admin/tenants/");
	} catch {
		/* fallback — API may not exist yet */
	}
	return { tenants };
};

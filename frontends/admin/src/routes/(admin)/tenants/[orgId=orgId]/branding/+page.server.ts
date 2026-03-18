import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals, params }) => {
	const api = createServerApiClient(locals.token);
	let branding: Record<string, string> = {};
	try {
		const result = await api.get(`/admin/configs/${params.orgId}`, {
			vertical: "branding",
		});
		branding = (result as { config?: Record<string, string> })?.config ?? {};
	} catch {
		/* fallback — API may not exist yet */
	}
	return { branding, orgId: params.orgId };
};

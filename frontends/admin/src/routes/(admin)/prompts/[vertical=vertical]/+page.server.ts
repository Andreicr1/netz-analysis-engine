import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals, params }) => {
	const api = createServerApiClient(locals.token);
	let prompts: unknown[] = [];
	try {
		prompts = await api.get(`/admin/prompts/${params.vertical}`);
	} catch {
		/* fallback — API may not be available yet */
	}
	return { prompts, vertical: params.vertical };
};

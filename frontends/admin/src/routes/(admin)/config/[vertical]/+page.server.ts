import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals, params }) => {
	const api = createServerApiClient(locals.token);
	let configs = [];
	try {
		configs = await api.get("/admin/configs/");
	} catch {
		/* fallback */
	}

	// Filter for this vertical
	const verticalConfigs = configs.filter((c: any) => c.vertical === params.vertical);

	return { configs: verticalConfigs, vertical: params.vertical };
};

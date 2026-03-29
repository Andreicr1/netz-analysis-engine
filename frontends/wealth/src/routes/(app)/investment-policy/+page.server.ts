import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);
	const [configsResult] = await Promise.allSettled([
		api.get("/admin/configs/"),
	]);
	const configs = configsResult.status === "fulfilled"
		? (configsResult.value as any[]).filter((c: any) => c.vertical === "wealth")
		: [];
	return { configs, token: locals.token };
};

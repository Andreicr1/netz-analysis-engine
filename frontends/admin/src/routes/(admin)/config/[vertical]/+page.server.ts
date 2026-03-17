import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals, params }) => {
	const api = createServerApiClient(locals.token);

	const [configsResult, invalidResult] = await Promise.allSettled([
		api.get("/admin/configs/"),
		api.get("/admin/configs/invalid"),
	]);

	const allConfigs = configsResult.status === "fulfilled" ? (configsResult.value as any[]) : [];
	const invalidConfigs = invalidResult.status === "fulfilled" ? (invalidResult.value as any[]) : [];

	// Filter for this vertical
	const verticalConfigs = allConfigs.filter((c: any) => c.vertical === params.vertical);

	return {
		configs: verticalConfigs,
		invalidConfigs,
		vertical: params.vertical,
	};
};

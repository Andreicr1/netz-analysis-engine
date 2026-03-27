import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);

	const [configsResult, invalidResult] = await Promise.allSettled([
		api.get("/admin/configs/"),
		api.get("/admin/configs/invalid"),
	]);

	const allConfigs = configsResult.status === "fulfilled" ? (configsResult.value as any[]) : [];
	const invalidConfigs = invalidResult.status === "fulfilled" ? (invalidResult.value as any[]) : [];

	// Filter for private_credit vertical only
	const verticalConfigs = allConfigs.filter((c: any) => c.vertical === "private_credit");

	return {
		configs: verticalConfigs,
		invalidConfigs,
		vertical: "private_credit",
	};
};

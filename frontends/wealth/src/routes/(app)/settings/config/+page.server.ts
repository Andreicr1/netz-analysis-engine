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

	// Filter for liquid_funds vertical only
	const verticalConfigs = allConfigs.filter((c: any) => c.vertical === "liquid_funds");

	return {
		configs: verticalConfigs,
		invalidConfigs,
		vertical: "liquid_funds",
	};
};

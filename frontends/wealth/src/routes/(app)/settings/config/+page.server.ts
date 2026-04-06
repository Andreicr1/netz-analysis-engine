import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

interface ConfigListItem {
	vertical: string;
	config_type: string;
	description?: string;
	has_override?: boolean;
}

interface InvalidConfigItem {
	vertical: string;
	config_type: string;
	reason?: string;
}

export const load: PageServerLoad = async ({ locals }) => {
	const token = locals.token as string;
	const api = createServerApiClient(token);

	const [configsResult, invalidResult] = await Promise.allSettled([
		api.get<ConfigListItem[]>("/admin/configs/"),
		api.get<InvalidConfigItem[]>("/admin/configs/invalid"),
	]);

	const allConfigs = configsResult.status === "fulfilled" ? configsResult.value : [];
	const invalidConfigs = invalidResult.status === "fulfilled" ? invalidResult.value : [];

	// Filter for liquid_funds vertical only
	const verticalConfigs = allConfigs.filter((c) => c.vertical === "liquid_funds");

	return {
		configs: verticalConfigs,
		invalidConfigs,
		vertical: "liquid_funds" as const,
		token,
	};
};

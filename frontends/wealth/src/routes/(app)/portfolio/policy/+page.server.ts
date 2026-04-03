import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

const CONFIG_TYPES = ["calibration", "scoring", "portfolio_profiles"] as const;

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);

	// Fetch actual config values (list endpoint only returns metadata, not values)
	const results = await Promise.allSettled(
		CONFIG_TYPES.map((ct) => api.get(`/admin/configs/liquid_funds/${ct}`)),
	);

	const configs = results
		.map((r, i) => {
			if (r.status === "fulfilled") {
				const res = r.value as { config: Record<string, any> };
				return {
					vertical: "liquid_funds",
					config_type: CONFIG_TYPES[i],
					value: res.config,
				};
			}
			return null;
		})
		.filter(Boolean);

	return { configs, token: locals.token };
};

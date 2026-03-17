/** Instrument Screener — fetch latest screening results and most recent run metadata. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [results, runs] = await Promise.allSettled([
		api.get("/screener/results", { limit: "500" }),
		api.get("/screener/runs", { limit: "1" }),
	]);

	return {
		results: results.status === "fulfilled" ? results.value : [],
		latestRun: runs.status === "fulfilled" && Array.isArray(runs.value) && runs.value.length > 0
			? runs.value[0]
			: null,
	};
};

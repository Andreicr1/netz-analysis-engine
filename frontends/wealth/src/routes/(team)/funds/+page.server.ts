/** Fund universe — fetch all funds and latest screener run. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [funds, screenerRuns] = await Promise.allSettled([
		api.get("/funds"),
		api.get("/screener/runs", { limit: "1" }),
	]);

	return {
		funds: funds.status === "fulfilled" ? funds.value : null,
		screenerRuns: screenerRuns.status === "fulfilled" ? screenerRuns.value : null,
	};
};

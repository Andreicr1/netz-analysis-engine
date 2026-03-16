/** Macro Intelligence — regional scores, regime hierarchy, committee reviews. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [scores, snapshot, regime, reviews] = await Promise.allSettled([
		api.get("/macro/scores"),
		api.get("/macro/snapshot"),
		api.get("/macro/regime"),
		api.get("/macro/reviews"),
	]);

	return {
		scores: scores.status === "fulfilled" ? scores.value : null,
		snapshot: snapshot.status === "fulfilled" ? snapshot.value : null,
		regime: regime.status === "fulfilled" ? regime.value : null,
		reviews: reviews.status === "fulfilled" ? reviews.value : null,
	};
};

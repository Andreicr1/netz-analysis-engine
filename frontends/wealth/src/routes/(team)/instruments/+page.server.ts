/** Instruments list — loads all instruments. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [instruments] = await Promise.allSettled([
		api.get("/instruments", { limit: 500 }),
	]);

	return {
		instruments: instruments.status === "fulfilled" ? instruments.value : [],
	};
};

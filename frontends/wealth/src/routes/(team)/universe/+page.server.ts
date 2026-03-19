/** Universe page — loads approved universe + pending approvals. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [universe, pending] = await Promise.allSettled([
		api.get("/universe"),
		api.get("/universe/pending"),
	]);

	return {
		universe: universe.status === "fulfilled" ? universe.value : [],
		pending: pending.status === "fulfilled" ? pending.value : [],
	};
};

/** Fund detail — fetch fund info. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [fund] = await Promise.allSettled([
		api.get(`/funds/${fundId}`),
	]);

	return {
		fund: fund.status === "fulfilled" ? fund.value : null,
		fundId,
	};
};

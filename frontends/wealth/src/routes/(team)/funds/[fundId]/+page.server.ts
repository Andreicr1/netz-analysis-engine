/** Fund detail — parallel fetch of fund info, risk metrics, and NAV history. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [fund, risk, nav] = await Promise.allSettled([
		api.get(`/funds/${fundId}`),
		api.get(`/funds/${fundId}/risk`),
		api.get(`/funds/${fundId}/nav`),
	]);

	return {
		fund: fund.status === "fulfilled" ? fund.value : null,
		risk: risk.status === "fulfilled" ? risk.value : null,
		nav: nav.status === "fulfilled" ? nav.value : null,
		fundId,
	};
};

/** DD Reports — list all DD reports across funds. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// DD reports are per-fund, so we list funds first then could load reports.
	// For now, the page will prompt user to select a fund.
	const [funds] = await Promise.allSettled([
		api.get("/funds"),
	]);

	return {
		funds: funds.status === "fulfilled" ? funds.value : null,
	};
};

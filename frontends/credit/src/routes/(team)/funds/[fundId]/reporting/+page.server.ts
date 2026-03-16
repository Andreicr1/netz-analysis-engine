/** Reporting overview — loads NAV snapshots, report packs. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [navSnapshots, reportPacks, statements] = await Promise.allSettled([
		api.get(`/funds/${fundId}/reports/nav/snapshots`),
		api.get(`/funds/${fundId}/reports/monthly-pack/list`),
		api.get(`/funds/${fundId}/reports/investor-statements`),
	]);

	return {
		navSnapshots: navSnapshots.status === "fulfilled" ? navSnapshots.value : { items: [] },
		reportPacks: reportPacks.status === "fulfilled" ? reportPacks.value : { items: [] },
		statements: statements.status === "fulfilled" ? statements.value : { items: [] },
		fundId,
	};
};

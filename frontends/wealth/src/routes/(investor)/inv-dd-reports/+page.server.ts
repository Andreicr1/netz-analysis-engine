/** Investor — approved DD reports for accessible funds. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Get funds the investor has access to
	const [fundsResult] = await Promise.allSettled([api.get("/funds")]);

	const funds = (fundsResult.status === "fulfilled"
		? fundsResult.value
		: []) as { fund_id: string; name: string }[];

	// Fetch DD reports per fund, filtering to approved/published
	const reportResults = await Promise.allSettled(
		funds.map((f) => api.get(`/dd-reports/funds/${f.fund_id}?status=approved`)),
	);

	const reports = funds.flatMap((f, i) => {
		const result = reportResults[i];
		if (result?.status === "fulfilled") {
			const items = (Array.isArray(result.value) ? result.value : []) as Record<string, unknown>[];
			return items.map((r) => ({
				...r,
				fund_name: f.name,
				fund_id: f.fund_id,
			}));
		}
		return [];
	});

	return { reports };
};

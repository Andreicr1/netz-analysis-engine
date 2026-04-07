/** DD Reports for fund — list report versions. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { DDReportSummary } from "$lib/types/dd-report";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [reports, fund] = await Promise.all([
		api.get<DDReportSummary[]>(`/dd-reports/funds/${params.fundId}`).catch(() => [] as DDReportSummary[]),
		api.get<{ id: string; name: string; ticker: string | null }>(`/funds/${params.fundId}`).catch(() => null),
	]);

	return {
		reports,
		fund,
		fundId: params.fundId!,
	};
};

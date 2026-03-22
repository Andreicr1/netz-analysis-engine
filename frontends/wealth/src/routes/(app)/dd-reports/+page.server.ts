/** DD Reports — list funds with available reports. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { DDReportSummary } from "$lib/types/dd-report";

interface FundBrief {
	id: string;
	name: string;
	ticker: string | null;
	isin: string | null;
	asset_class: string | null;
	geography: string | null;
}

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const funds = await api.get<FundBrief[]>("/funds").catch(() => [] as FundBrief[]);

	return { funds };
};

/** DD Reports — list all DD reports for the tenant with statuses. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { DDReportListItem } from "$lib/types/dd-report";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const statusFilter = url.searchParams.get("status") ?? undefined;
	const params: Record<string, string> = {};
	if (statusFilter) params.status = statusFilter;

	const reports = await api.get<DDReportListItem[]>("/dd-reports/", params).catch(() => [] as DDReportListItem[]);

	return { reports, statusFilter: statusFilter ?? null };
};

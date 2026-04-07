/** DD Report detail — full report with chapters, plus actor context for approval. */
import type { PageServerLoad } from "./$types";
import { error } from "@sveltejs/kit";
import { createServerApiClient } from "$lib/api/client";
import type { DDReportFull } from "$lib/types/dd-report";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const report = await api.get<DDReportFull>(`/dd-reports/${params.reportId}`)
		.catch(() => { throw error(404, "Report not found"); });

	return {
		report,
		fundId: params.fundId!,
		reportId: params.reportId!,
		actorId: actor?.user_id ?? null,
		actorRole: actor?.role ?? null,
	};
};

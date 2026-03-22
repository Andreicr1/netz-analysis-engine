/** DD Report detail — loads full report with chapters + actor for approval. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { error } from "@sveltejs/kit";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);
	const { fundId, reportId } = params;

	const [report] = await Promise.allSettled([
		api.get(`/dd-reports/${reportId}`),
	]);

	if (report.status === "rejected") {
		throw error(404, "DD Report not found.");
	}

	return {
		report: report.value as Record<string, unknown>,
		fundId,
		reportId,
		actorId: actor.user_id as string,
		actorRole: actor.role as string,
	};
};

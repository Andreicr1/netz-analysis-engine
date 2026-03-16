/** Dashboard — parallel fetch of all summary endpoints. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Parallel fetch — all dashboard endpoints
	const [portfolioSummary, pipelineSummary, pipelineAnalytics, macroSnapshot, complianceAlerts, taskInbox] =
		await Promise.allSettled([
			api.get("/dashboard/portfolio-summary"),
			api.get("/dashboard/pipeline-summary"),
			api.get("/dashboard/pipeline-analytics"),
			api.get("/dashboard/macro-snapshot"),
			api.get("/dashboard/compliance-alerts"),
			api.get("/dashboard/task-inbox"),
		]);

	return {
		portfolioSummary: portfolioSummary.status === "fulfilled" ? portfolioSummary.value : null,
		pipelineSummary: pipelineSummary.status === "fulfilled" ? pipelineSummary.value : null,
		pipelineAnalytics: pipelineAnalytics.status === "fulfilled" ? pipelineAnalytics.value : null,
		macroSnapshot: macroSnapshot.status === "fulfilled" ? macroSnapshot.value : null,
		complianceAlerts: complianceAlerts.status === "fulfilled" ? complianceAlerts.value : null,
		taskInbox: taskInbox.status === "fulfilled" ? taskInbox.value : null,
	};
};

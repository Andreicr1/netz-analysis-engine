/** System health page — loads worker status, pipeline stats, tenant usage. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [workers, pipelines, usage] = await Promise.allSettled([
		api.get<unknown[]>("/admin/health/workers"),
		api.get("/admin/health/pipelines"),
		api.get<unknown[]>("/admin/health/usage"),
	]);

	return {
		workers: workers.status === "fulfilled" ? workers.value : [],
		pipelines: pipelines.status === "fulfilled" ? pipelines.value : { documents_processed: 0, queue_depth: 0, error_rate: 0 },
		usage: usage.status === "fulfilled" ? usage.value : [],
	};
};

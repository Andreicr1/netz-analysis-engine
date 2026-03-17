import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);

	let services: Array<{
		name: string;
		status: string;
		latency_ms: number | null;
		error: string | null;
	}> = [];
	let workers: Array<{
		name: string;
		status: string;
		last_run: string | null;
		duration_ms: number | null;
		error_count: number;
	}> = [];
	let pipelines = { docs_processed: 0, queue_depth: 0, error_rate: 0 };

	try {
		services = await api.get("/admin/health/services");
	} catch {
		/* fallback to empty */
	}

	try {
		workers = await api.get("/admin/health/workers");
	} catch {
		/* fallback to empty */
	}

	try {
		pipelines = await api.get("/admin/health/pipelines");
	} catch {
		/* fallback */
	}

	return { services, workers, pipelines };
};

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

type ServiceHealthRow = {
	name: string;
	status: string;
	latency_ms: number | null;
	error: string | null;
	checked_at?: string | null;
};

type WorkerStatusRow = {
	name: string;
	status: string;
	last_run: string | null;
	duration_ms: number | null;
	error_count: number;
};

type PipelineStats = {
	docs_processed: number;
	queue_depth: number;
	error_rate: number;
	checked_at?: string | null;
};

type SectionErrors = {
	services: string | null;
	workers: string | null;
	pipelines: string | null;
};

function toErrorMessage(error: unknown): string {
	if (error instanceof Error) {
		return error.message;
	}

	return "Unable to load health data.";
}

export const load: PageServerLoad = async ({ locals }) => {
	const api = createServerApiClient(locals.token);

	const [servicesResult, workersResult, pipelinesResult] = await Promise.allSettled([
		api.get("/admin/health/services"),
		api.get("/admin/health/workers"),
		api.get("/admin/health/pipelines"),
	]);

	const services = servicesResult.status === "fulfilled" ? (servicesResult.value as ServiceHealthRow[]) : [];
	const workers = workersResult.status === "fulfilled" ? (workersResult.value as WorkerStatusRow[]) : [];
	const pipelines =
		pipelinesResult.status === "fulfilled"
			? (pipelinesResult.value as PipelineStats)
			: { docs_processed: 0, queue_depth: 0, error_rate: 0 };

	const sectionErrors: SectionErrors = {
		services: servicesResult.status === "rejected" ? toErrorMessage(servicesResult.reason) : null,
		workers: workersResult.status === "rejected" ? toErrorMessage(workersResult.reason) : null,
		pipelines: pipelinesResult.status === "rejected" ? toErrorMessage(pipelinesResult.reason) : null,
	};

	return {
		services,
		workers,
		pipelines,
		sectionErrors,
		hasDegradedState:
			Boolean(sectionErrors.services || sectionErrors.workers || sectionErrors.pipelines) ||
			services.some((service) => service.status !== "ok"),
	};
};

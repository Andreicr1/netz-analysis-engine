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
	checked_at?: string | null;
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
	const token = locals.token as string;
	const api = createServerApiClient(token);

	const [servicesResult, workersResult, pipelinesResult] = await Promise.allSettled([
		api.get<ServiceHealthRow[]>("/admin/health/services"),
		api.get<WorkerStatusRow[]>("/admin/health/workers"),
		api.get<PipelineStats>("/admin/health/pipelines"),
	]);

	const services = servicesResult.status === "fulfilled" ? servicesResult.value : [];
	const workers = workersResult.status === "fulfilled" ? workersResult.value : [];
	const pipelines =
		pipelinesResult.status === "fulfilled"
			? pipelinesResult.value
			: { docs_processed: 0, queue_depth: 0, error_rate: 0, checked_at: null };

	const sectionErrors: SectionErrors = {
		services: servicesResult.status === "rejected" ? toErrorMessage(servicesResult.reason) : null,
		workers: workersResult.status === "rejected" ? toErrorMessage(workersResult.reason) : null,
		pipelines: pipelinesResult.status === "rejected" ? toErrorMessage(pipelinesResult.reason) : null,
	};

	return {
		token,
		services,
		workers,
		pipelines,
		sectionErrors,
		hasDegradedState:
			Boolean(sectionErrors.services || sectionErrors.workers || sectionErrors.pipelines) ||
			services.some((service) => service.status !== "ok"),
	};
};

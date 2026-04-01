/** Screening Run Detail — shows results for a specific run. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreeningRun, ScreeningResult } from "$lib/types/screening";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [run, allResults] = await Promise.all([
		api.get<ScreeningRun>(`/screener/runs/${params.runId}`).catch(() => null),
		api.get<ScreeningResult[]>("/screener/results", { limit: "1000" }).catch(() => [] as ScreeningResult[]),
	]);

	// Filter results belonging to this run
	const results = allResults.filter((r) => r.run_id === params.runId);

	return { run, results };
};

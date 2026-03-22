/** Screener SSR load — fetches latest results + last run metadata. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreeningResult, ScreeningRun } from "$lib/types/screening";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [results, runs] = await Promise.all([
		api.get<ScreeningResult[]>("/screener/results", { limit: "500" }).catch(() => [] as ScreeningResult[]),
		api.get<ScreeningRun[]>("/screener/runs", { limit: "1" }).catch(() => [] as ScreeningRun[]),
	]);

	return {
		results,
		lastRun: runs[0] ?? null,
	};
};

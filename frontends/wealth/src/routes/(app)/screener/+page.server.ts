/** Unified Screener SSR — managers (paginated) + screening results in parallel. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreeningResult, ScreeningRun } from "$lib/types/screening";
import type { ScreenerPage } from "$lib/types/manager-screener";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Manager params from URL
	const mgrParams = new URLSearchParams();
	for (const [key, value] of url.searchParams.entries()) {
		mgrParams.append(key, value);
	}
	if (!mgrParams.has("page")) mgrParams.set("page", "1");
	if (!mgrParams.has("page_size")) mgrParams.set("page_size", "25");

	const [screener, results, runs] = await Promise.all([
		api.get<ScreenerPage>(`/manager-screener/?${mgrParams.toString()}`).catch(() => null),
		api.get<ScreeningResult[]>("/screener/results", { limit: "500" }).catch(() => [] as ScreeningResult[]),
		api.get<ScreeningRun[]>("/screener/runs", { limit: "1" }).catch(() => [] as ScreeningRun[]),
	]);

	return {
		screener,
		results,
		lastRun: runs[0] ?? null,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

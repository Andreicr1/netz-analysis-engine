/** Manager Screener — server load with URL-driven filters. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Forward all searchParams as query string to the backend
	const params = new URLSearchParams();
	for (const [key, value] of url.searchParams.entries()) {
		params.append(key, value);
	}

	// Defaults
	if (!params.has("page")) params.set("page", "1");
	if (!params.has("page_size")) params.set("page_size", "25");

	const qs = params.toString();

	const [screenerResult] = await Promise.allSettled([
		api.get(`/manager-screener/?${qs}`),
	]);

	return {
		screener: screenerResult.status === "fulfilled" ? screenerResult.value : null,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};

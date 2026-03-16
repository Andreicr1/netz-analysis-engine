/** Allocation — fetch strategic, tactical, and effective for all profiles. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profile = url.searchParams.get("profile") ?? "moderate";

	const [strategic, tactical, effective] = await Promise.allSettled([
		api.get(`/allocation/${profile}/strategic`),
		api.get(`/allocation/${profile}/tactical`),
		api.get(`/allocation/${profile}/effective`),
	]);

	return {
		profile,
		strategic: strategic.status === "fulfilled" ? strategic.value : null,
		tactical: tactical.status === "fulfilled" ? tactical.value : null,
		effective: effective.status === "fulfilled" ? effective.value : null,
	};
};

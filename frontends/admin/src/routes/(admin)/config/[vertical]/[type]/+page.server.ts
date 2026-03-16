/** Config editor page — loads diff (default vs override vs merged). */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { vertical, type } = params;

	const [diff] = await Promise.allSettled([
		api.get(`/admin/configs/${vertical}/${type}/diff`),
	]);

	return {
		vertical,
		configType: type,
		diff: diff.status === "fulfilled" ? diff.value : { default: {}, override: {}, merged: {}, override_version: null },
	};
};

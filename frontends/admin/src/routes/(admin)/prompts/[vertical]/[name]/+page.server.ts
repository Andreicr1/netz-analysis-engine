/** Prompt editor page — loads resolved prompt + version history. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { vertical, name } = params;

	const [prompt, versions] = await Promise.allSettled([
		api.get(`/admin/prompts/${vertical}/${name}`),
		api.get(`/admin/prompts/${vertical}/${name}/versions`),
	]);

	return {
		vertical,
		templateName: name,
		prompt: prompt.status === "fulfilled" ? prompt.value : null,
		versions: versions.status === "fulfilled" ? versions.value : [],
	};
};

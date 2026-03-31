/** Universe — approved instruments + pending approvals. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UniverseAsset, UniverseApproval } from "$lib/types/universe";

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();

	if (!token) {
		return { assets: [] as UniverseAsset[], pending: [] as UniverseApproval[], actorRole: null };
	}

	const api = createServerApiClient(token);

	const [assetsResult, pendingResult] = await Promise.allSettled([
		api.get<UniverseAsset[]>("/universe"),
		api.get<UniverseApproval[]>("/universe/pending"),
	]);

	return {
		assets: assetsResult.status === "fulfilled" ? assetsResult.value : [],
		pending: pendingResult.status === "fulfilled" ? pendingResult.value : [],
		actorRole: actor?.role ?? null,
	};
};

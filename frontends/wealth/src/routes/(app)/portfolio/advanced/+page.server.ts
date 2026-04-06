/** Advanced — load portfolio funds for selector. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UniverseAsset } from "$lib/types/universe";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) return { instruments: [] };

	const api = createServerApiClient(token);
	const instruments = await api
		.get<UniverseAsset[]>("/universe")
		.catch(() => [] as UniverseAsset[]);

	return { instruments };
};

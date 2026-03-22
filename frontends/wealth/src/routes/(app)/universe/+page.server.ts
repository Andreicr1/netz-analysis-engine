/** Universe — approved instruments with optional risk data. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UniverseAsset } from "$lib/types/universe";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const assets = await api.get<UniverseAsset[]>("/universe").catch(() => [] as UniverseAsset[]);

	return { assets };
};

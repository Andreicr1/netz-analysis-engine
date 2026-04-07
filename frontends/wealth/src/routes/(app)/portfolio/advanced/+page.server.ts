/** Advanced — load portfolio funds + model portfolios for selector. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UniverseAsset } from "$lib/types/universe";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) return { instruments: [], portfolios: [] };

	const api = createServerApiClient(token);

	const [instruments, portfolios] = await Promise.all([
		api.get<UniverseAsset[]>("/universe").catch(() => [] as UniverseAsset[]),
		api.get<ModelPortfolio[]>("/model-portfolios").catch(() => [] as ModelPortfolio[]),
	]);

	return { instruments, portfolios };
};

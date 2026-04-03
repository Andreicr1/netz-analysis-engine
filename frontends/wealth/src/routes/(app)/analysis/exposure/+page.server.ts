/** Exposure — geographic x sector heatmap. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ExposureMatrix } from "$lib/types/exposure";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [geographic, sector, portfolios] = await Promise.all([
		api.get<ExposureMatrix>("/wealth/exposure/matrix", { dimension: "geographic" }).catch(() => null),
		api.get<ExposureMatrix>("/wealth/exposure/matrix", { dimension: "sector" }).catch(() => null),
		api.get<Array<unknown>>("/portfolios").catch(() => [] as unknown[]),
	]);

	return { geographic, sector, portfolioCount: portfolios?.length ?? 0 };
};

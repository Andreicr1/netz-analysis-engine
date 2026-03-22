/** Exposure — geographic x sector heatmap. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ExposureMatrix } from "$lib/types/exposure";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [geographic, sector] = await Promise.all([
		api.get<ExposureMatrix>("/exposure/matrix", { dimension: "geographic" }).catch(() => null),
		api.get<ExposureMatrix>("/exposure/matrix", { dimension: "sector" }).catch(() => null),
	]);

	return { geographic, sector };
};

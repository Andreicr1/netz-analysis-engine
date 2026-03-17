/** Exposure Monitor — geographic and sector exposure heatmaps + data freshness. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const aggregation = url.searchParams.get("aggregation") ?? "portfolio";

	const [geoMatrix, sectorMatrix, metadata] = await Promise.allSettled([
		api.get(`/wealth/exposure/matrix?dimension=geographic&aggregation=${aggregation}`),
		api.get(`/wealth/exposure/matrix?dimension=sector&aggregation=${aggregation}`),
		api.get("/wealth/exposure/metadata"),
	]);

	return {
		aggregation,
		geoMatrix: geoMatrix.status === "fulfilled" ? geoMatrix.value : null,
		sectorMatrix: sectorMatrix.status === "fulfilled" ? sectorMatrix.value : null,
		metadata: metadata.status === "fulfilled" ? metadata.value : null,
	};
};

/** Entity Analytics Vitrine — polymorphic analytics for funds and model portfolios. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { EntityAnalyticsResponse } from "$lib/types/entity-analytics";
import type { PeerGroupResult, ActiveShareResult } from "$lib/types/analytics";

export const load: PageServerLoad = async ({ parent, url, params }) => {
	const { entityId } = params;
	const window = url.searchParams.get("window") ?? "1y";
	const benchmarkId = url.searchParams.get("benchmark_id");

	const { token } = await parent();
	const api = createServerApiClient(token);

	const qp: Record<string, string> = { window };
	if (benchmarkId) qp.benchmark_id = benchmarkId;

	// Fetch all data in parallel — entity analytics, peer group, active share
	const [analytics, peerGroup, activeShare] = await Promise.all([
		api
			.get<EntityAnalyticsResponse>(`/analytics/entity/${entityId}`, qp)
			.catch(() => null),
		api
			.get<PeerGroupResult>(`/analytics/peer-group/${entityId}`)
			.catch(() => null),
		benchmarkId
			? api
					.get<ActiveShareResult>(`/analytics/active-share/${entityId}`, {
						benchmark_id: benchmarkId,
					})
					.catch(() => null)
			: Promise.resolve(null),
	]);

	return { analytics, peerGroup, activeShare, entityId, window };
};

/** Deal detail — loads deal, IC memo status, stage timeline. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { error } from "@sveltejs/kit";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId, dealId } = params;

	// Parallel fetch deal data
	const [deal, stageTimeline, icMemo, votingStatus] = await Promise.allSettled([
		api.get(`/funds/${fundId}/deals/${dealId}`),
		api.get(`/funds/${fundId}/deals/${dealId}/stage-timeline`),
		api.get(`/funds/${fundId}/deals/${dealId}/ic-memo`),
		api.get(`/funds/${fundId}/deals/${dealId}/ic-memo/voting-status`),
	]);

	if (deal.status === "rejected") {
		throw error(404, "Deal not found.");
	}

	return {
		deal: deal.value as Record<string, unknown>,
		stageTimeline: stageTimeline.status === "fulfilled" ? stageTimeline.value : null,
		icMemo: icMemo.status === "fulfilled" ? icMemo.value : null,
		votingStatus: votingStatus.status === "fulfilled" ? votingStatus.value : null,
		fundId,
		dealId,
	};
};

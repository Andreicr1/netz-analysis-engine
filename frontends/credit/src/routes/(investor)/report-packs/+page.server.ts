/** Investor — list published report packs. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	// Investor sees all funds in their org; use first fund or param
	const fundId = url.searchParams.get("fund_id");
	if (!fundId) {
		return { packs: [], fundId: null };
	}

	let packs: Record<string, unknown>[] = [];
	try {
		packs = await api.get(`/funds/${fundId}/investor/report-packs`);
	} catch {
		// Empty state
	}

	return { packs, fundId };
};

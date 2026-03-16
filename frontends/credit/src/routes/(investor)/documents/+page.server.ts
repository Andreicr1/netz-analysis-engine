/** Investor — list approved-for-distribution documents. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const fundId = url.searchParams.get("fund_id");
	if (!fundId) {
		return { documents: [], fundId: null };
	}

	let documents: Record<string, unknown>[] = [];
	try {
		const result = await api.get<{ items: Record<string, unknown>[] }>(
			`/funds/${fundId}/investor/documents`,
		);
		documents = result.items ?? [];
	} catch {
		// Empty state
	}

	return { documents, fundId };
};

/** Investor — list published investor statements. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const fundId = url.searchParams.get("fund_id");
	if (!fundId) {
		return { statements: [], fundId: null };
	}

	let statements: Record<string, unknown>[] = [];
	try {
		const result = await api.get<{ items: Record<string, unknown>[] }>(
			`/funds/${fundId}/investor/statements`,
		);
		statements = result.items ?? [];
	} catch {
		// Empty state
	}

	return { statements, fundId };
};

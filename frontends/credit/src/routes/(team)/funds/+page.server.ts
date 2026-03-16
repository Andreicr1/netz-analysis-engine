/** Fund selector — loads fund list, redirects to first fund if only one. */
import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

interface Fund {
	id: string;
	name: string;
	status: string;
}

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	let funds: Fund[] = [];
	try {
		const res = await api.get<{ items: Fund[] }>("/funds");
		funds = res.items ?? [];
	} catch {
		funds = [];
	}

	// If exactly one fund, redirect directly
	if (funds.length === 1 && funds[0]) {
		throw redirect(303, `/funds/${funds[0].id}/pipeline`);
	}

	return { funds };
};

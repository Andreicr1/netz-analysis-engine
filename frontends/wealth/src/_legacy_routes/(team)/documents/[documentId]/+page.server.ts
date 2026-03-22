/** Wealth document detail — loads single document by ID. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [document] = await Promise.allSettled([
		api.get(`/wealth/documents/${params.documentId}`),
	]);

	return {
		document: document.status === "fulfilled" ? document.value : null,
	};
};
